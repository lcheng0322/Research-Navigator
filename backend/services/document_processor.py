import logging
import re
import tempfile
import requests
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple, cast, Optional
from difflib import SequenceMatcher

import pandas as pd
from sqlalchemy.orm import Session
from unstructured.partition.auto import partition
from unstructured.documents.elements import Element, Title, Table
from langchain_text_splitters import NLTKTextSplitter

# Ensure NLTK punkt tokenizer is available (required by NLTKTextSplitter)
import nltk
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab', quiet=True)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)

from ..models.document import Document, DocumentMetadata
from .llm_service import get_llm_response
from . import vector_store_service
from ..core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def delete_document_and_vectors(db: Session, document_id: int) -> Document:
    """
    Coordinates the deletion of a document from both the relational database
    and the vector database to ensure data consistency.
    """
    logging.info(f"Starting deletion process for document_id: {document_id}")

    # 1. Find the document in the relational database
    db_document = db.query(Document).filter(Document.id == document_id).first()
    if not db_document:
        raise ValueError(f"Document with ID {document_id} not found.")

    # 2. Delete all associated vectors from the vector database first
    try:
        vector_store_service.delete_document_vectors(document_id)
        logging.info(f"Successfully deleted vectors for document_id: {document_id}")
    except Exception as e:
        logging.error(f"Critical error: Failed to delete vectors for document_id: {document_id}. Aborting deletion. Error: {e}")
        raise

    # 3. Delete the document from the relational database
    db.delete(db_document)
    db.commit()
    logging.info(f"Successfully deleted document record for document_id: {document_id}")

    return db_document


def _extract_and_store_metadata(db: Session, document_id: int, elements: List[Element]):
    """
    Extracts metadata using a three-tier strategy (DOI -> CrossRef -> LLM)
    and stores it in the database.
    """
    logging.info(f"Starting metadata extraction for document_id: {document_id}")

    # --- Tier 1: Find DOI using Regex (enhanced) ---
    doi_pattern = re.compile(r'\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b', re.IGNORECASE)
    doi_url_pattern = re.compile(r'https?://doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)', re.IGNORECASE)
    doi_with_prefix_pattern = re.compile(r'doi[:\s]*(10\.\d{4,9}/[-._;()/:A-Z0-9]+)', re.IGNORECASE)
    found_doi: Optional[str] = None

    primary_text = " ".join([el.text for el in elements[:20]])
    extended_text = " ".join([el.text for el in elements[:120]])
    text_for_doi_scan = primary_text if primary_text else extended_text

    def _normalize_doi(raw_doi: str) -> str:
        cleaned = raw_doi.strip().strip(".,;:")
        cleaned = re.sub(r'^https?://doi\.org/', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'^doi[:\s]*', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace(" ", "")
        return cleaned

    def _is_plausible_doi(candidate: str) -> bool:
        return bool(re.fullmatch(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', candidate, flags=re.IGNORECASE))

    def _score_doi(candidate: str, location_score: float) -> float:
        score = location_score
        if "." in candidate:
            score += 0.2
        if "/" in candidate:
            score += 0.2
        if len(candidate) >= 6:
            score += min(len(candidate) / 50.0, 0.4)
        if re.match(r'10\.\d{4}/', candidate):
            score += 0.2
        return score

    def _extract_candidates(source_text: str, base_score: float) -> Dict[str, float]:
        normalized_text = re.sub(r"\s+", " ", source_text)
        normalized_text = re.sub(r"(10\.\d{4,9})\s*/\s*([-._;()/:A-Z0-9]+)", r"\1/\2", normalized_text, flags=re.IGNORECASE)
        extracted: Dict[str, float] = {}
        for pattern in (doi_pattern, doi_url_pattern, doi_with_prefix_pattern):
            matches = pattern.findall(normalized_text)
            if not matches:
                continue
            for match in matches:
                candidate = match if isinstance(match, str) else match[0]
                normalized_candidate = _normalize_doi(candidate)
                if not _is_plausible_doi(normalized_candidate):
                    continue
                extracted[normalized_candidate] = max(extracted.get(normalized_candidate, 0.0), base_score)
        return extracted

    candidate_scores: Dict[str, float] = {}
    if text_for_doi_scan:
        candidate_scores.update(_extract_candidates(text_for_doi_scan, 1.0))
    if extended_text:
        for candidate, base_score in _extract_candidates(extended_text, 0.6).items():
            candidate_scores[candidate] = max(candidate_scores.get(candidate, 0.0), base_score)

    if candidate_scores:
        ranked_candidates = sorted(
            candidate_scores.items(),
            key=lambda item: _score_doi(item[0], item[1]),
            reverse=True
        )
        for candidate, location_score in ranked_candidates:
            if not _is_plausible_doi(candidate):
                continue

            found_doi = candidate
            logging.info(f"Tier 1: Found DOI '{found_doi}' for document_id: {document_id}")
            break
        else:
            logging.info(f"Tier 1: DOI-like strings detected but none passed plausibility or validation checks for document_id: {document_id}")

    def _store_metadata_entries(entries: Dict[str, Any]) -> None:
        for key, value in entries.items():
            if value is None:
                continue
            if isinstance(value, list):
                value_str = "; ".join(str(item) for item in value if item is not None)
            else:
                value_str = str(value)
            if not value_str.strip():
                continue
            db.add(DocumentMetadata(document_id=document_id, key=key, value=value_str))

    def _extract_year(message: Dict[str, Any]) -> Optional[str]:
        for key in ("published-print", "published-online", "issued", "created"):
            date_parts = message.get(key, {}).get("date-parts")
            if date_parts and isinstance(date_parts, list) and date_parts[0]:
                year_candidate = date_parts[0][0]
                if year_candidate:
                    return str(year_candidate)
        return None

    def _persist_crossref_message(message: Dict[str, Any]) -> bool:
        metadata_to_store: Dict[str, Any] = {}
        titles = message.get("title") or []
        if titles:
            metadata_to_store["title"] = ", ".join(filter(None, titles))
        authors = message.get("author") or []
        if authors:
            formatted_authors = []
            for author in authors:
                given = (author.get("given") or "").strip()
                family = (author.get("family") or "").strip()
                full_name = " ".join(part for part in [given, family] if part)
                if full_name:
                    formatted_authors.append(full_name)
            if formatted_authors:
                metadata_to_store["authors"] = formatted_authors
        year = _extract_year(message)
        if year:
            metadata_to_store["publication_year"] = year
        containers = message.get("container-title") or []
        if containers:
            metadata_to_store["journal"] = ", ".join(filter(None, containers))
        abstract_text = message.get("abstract")
        if abstract_text:
            metadata_to_store["abstract"] = abstract_text
        crossref_doi = message.get("DOI")
        if crossref_doi:
            normalized = _normalize_doi(crossref_doi)
            if normalized and _is_plausible_doi(normalized):
                metadata_to_store["doi"] = normalized
        if not metadata_to_store:
            return False
        _store_metadata_entries(metadata_to_store)
        logging.info(f"Persisted metadata from CrossRef for document_id: {document_id}")
        return True

    def _fetch_crossref_by_doi(doi: str) -> Optional[Dict[str, Any]]:
        for attempt in range(3):
            try:
                url = f"https://api.crossref.org/works/{doi}"
                response = requests.get(url, timeout=settings.PROCESSOR_CROSSREF_TIMEOUT)
                if response.status_code == 200:
                    return response.json().get("message", {})
                logging.warning(f"Tier 2: CrossRef returned status {response.status_code} for DOI {doi} and document_id {document_id}")
            except requests.RequestException as exc:
                logging.warning(f"Tier 2: CrossRef DOI lookup failed on attempt {attempt + 1}/3 for document_id {document_id}. Error: {exc}")
            time.sleep(1)  # Wait 1 second before retrying
        return None

    # --- Tier 2: Query CrossRef API if DOI is found ---
    if found_doi:
        crossref_message = _fetch_crossref_by_doi(found_doi)
        if crossref_message and _persist_crossref_message(crossref_message):
            logging.info(f"Tier 2: Successfully fetched metadata from CrossRef for document_id: {document_id}")
            return

    # --- Tier 3: Fallback to LLM for metadata extraction ---
    logging.info(f"Tier 3: Falling back to LLM for metadata extraction for document_id: {document_id}")
    try:
        first_page_text = " ".join([el.text for el in elements if getattr(el.metadata, 'page_number', 1) == 1])

        prompt = f'''
        As a specialist librarian, analyze the text from the first page of a research paper and extract its core metadata.
        Respond ONLY with a single, valid JSON object containing the following keys: "title", "authors" (as a list of strings), "publication_year" (as an integer), "journal" (also known as source or venue), and "abstract".
        If a value is not found, use null.

        Text:
        ---
        {first_page_text[:4000]}
        ---

        JSON Output:
        '''

        response_text = get_llm_response(prompt, use_reasoner=False)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            raise ValueError("LLM response did not contain a valid JSON object.")

        metadata_json = json.loads(json_match.group(0))

        cleaned_entries: Dict[str, Any] = {}
        for key, value in metadata_json.items():
            if not value:
                continue
            if key == "authors" and isinstance(value, list):
                cleaned_entries[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                cleaned_entries[key] = str(value).strip()
        if cleaned_entries:
            _store_metadata_entries(cleaned_entries)
            logging.info(f"Tier 3: Successfully extracted metadata using LLM for document_id: {document_id}")

    except Exception as e:
        logging.error(f"Tier 3: LLM metadata extraction failed for document_id: {document_id}. Error: {e}")


def _get_metadata_as_dict(db: Session, document_id: int) -> Dict[str, Any]:
    """
    Retrieves all metadata for a document from the database and returns it as a single dictionary.
    This is used to inject a consistent set of metadata into every chunk.
    """
    metadata_records = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == document_id).all()
    doc = db.query(Document).filter(Document.id == document_id).first()

    metadata_dict: Dict[str, Any] = {str(meta.key): meta.value for meta in metadata_records}
    
    # Ensure core fields are present for consistency
    metadata_dict['document_id'] = str(document_id)
    if doc:
        metadata_dict['source'] = doc.file_name

    # Convert publication_year to int if it exists
    if 'publication_year' in metadata_dict and metadata_dict['publication_year'] is not None:
        try:
            metadata_dict['publication_year'] = int(float(metadata_dict['publication_year']))
        except (ValueError, TypeError):
            logging.warning(f"Could not convert publication_year '{metadata_dict['publication_year']}' to int for document_id {document_id}.")
    
    return metadata_dict


def _generate_summary(
    text_to_summarize: str,
    core_metadata: Dict[str, Any],
    summary_type: str,
    chapter_title: str | None = None,
    start_page: int | None = None
) -> Dict[str, Any]:
    """
    Generates a summary for a given text block, using a base metadata dictionary.
    """
    document_id = core_metadata.get("document_id", -1)
    logging.info(f"Generating {summary_type} summary for document_id: {document_id}" + (f" - Chapter: {chapter_title}" if chapter_title else ""))
    
    if summary_type == "chapter":
        prompt_intro = f"Based on the following text from the chapter titled '{chapter_title}', please provide a concise summary of this chapter."
    else: # full
        prompt_intro = f"Based on the following text from a document, please provide a concise, comprehensive summary of the entire document."

    prompt = f'''
    {prompt_intro}
    The summary should capture the key points, arguments, and conclusions of the text.

    Text:
    ---
    {text_to_summarize[:settings.PROCESSOR_LLM_SUMMARY_TRUNCATION]}
    ---

    Concise Summary:
    '''
    summary_text = get_llm_response(prompt, use_reasoner=False)
    
    summary_metadata = core_metadata.copy()
    summary_metadata.update({
        "is_summary": True,
        "summary_type": summary_type,
    })

    if summary_type == "chapter":
        summary_metadata["chapter_title"] = chapter_title or "Untitled Chapter"
        summary_metadata["page_number"] = str(start_page or -1)
    else: # full
        summary_metadata["page_number"] = "-1"

    return {"text": summary_text, "metadata": summary_metadata}

# --- NEW FUNCTIONS START HERE ---

def _filter_elements(elements: List[Element]) -> List[Element]:
    """Filters out low-value sections like references, appendices, and headers/footers."""
    # 扩展的低价值区域模式，支持更多格式和语言
    low_value_section_pattern = re.compile(
        r'^(\d+\.?\s*)?(references?|bibliography|bibliographies|acknowledgements?|appendix|appendices|'
        r'acknowledgments?|literature cited|works cited|cited literature|sources?|'
        r'references? and notes?|bibliography and references?|'
        r'参考文献|引用文献|文献引用|附录|致谢|'
        r'referências|références|literaturverzeichnis|bibliografia)', 
        re.IGNORECASE
    )
    
    # 参考文献内容模式 - 用于识别没有明确标题的参考文献
    reference_content_pattern = re.compile(
        r'^\s*\[?\d+\]?\s*[A-Z][^.]*\.\s*[A-Z][^.]*\.\s*\(\d{4}\)|'  # 标准学术引用格式
        r'^\s*[A-Z][a-z]+,\s*[A-Z]\.\s*[A-Z]?\.\s*\(\d{4}\)|'       # 作者, 首字母. (年份)
        r'^\s*\[?\d+\]?\s*[A-Z][^,]*,\s*[^,]*,\s*\d{4}',            # [数字] 作者, 标题, 年份
        re.MULTILINE
    )
    
    filtered_elements = []
    in_low_value_section = False
    consecutive_reference_like = 0  # 连续的类似参考文献的元素计数
    
    for i, el in enumerate(elements):
        if in_low_value_section:
            continue

        # 检查是否是明确的低价值区域标题
        if isinstance(el, Title) and low_value_section_pattern.match(el.text.strip()):
            in_low_value_section = True
            logging.info(f"Detected start of low-value section by title: '{el.text}'. Discarding subsequent elements.")
            continue
        
        # 检查是否是没有标题的参考文献区域
        if not isinstance(el, Title) and el.text and el.text.strip():
            if reference_content_pattern.match(el.text.strip()):
                consecutive_reference_like += 1
                # 如果连续3个元素都像参考文献，认为进入了参考文献区域
                if consecutive_reference_like >= 3:
                    in_low_value_section = True
                    logging.info(f"Detected start of reference section by content pattern. Discarding subsequent elements.")
                    # 移除之前误加入的参考文献元素
                    filtered_elements = filtered_elements[:-2]  # 移除前两个可能的参考文献
                    continue
            else:
                consecutive_reference_like = 0
        else:
            consecutive_reference_like = 0
        
        # 过滤页眉、页脚等
        if el.category in ["Header", "Footer", "PageBreak"]:
            continue
        
        # 额外检查：如果文本内容看起来像参考文献但没有被上面的规则捕获
        if (el.text and len(el.text.strip()) > 20 and 
            (el.text.count('(') > 2 or el.text.count('[') > 2) and
            re.search(r'\b(19|20)\d{2}\b', el.text)):  # 包含年份
            # 检查是否包含多个典型的参考文献指示词
            ref_indicators = ['doi:', 'http://', 'https://', 'vol.', 'pp.', 'journal', 'proceedings']
            indicator_count = sum(1 for indicator in ref_indicators if indicator.lower() in el.text.lower())
            if indicator_count >= 2:
                logging.info(f"Skipping potential reference content: '{el.text[:100]}...'")
                continue
            
        filtered_elements.append(el)
        
    return filtered_elements

def _get_title_level(element: Title) -> int:
    """Heuristically determines the level of a title element."""
    match = re.match(r'^(\d+(\.\d+)*)', element.text)
    if match:
        return match.group(1).count('.') + 1
    
    level = getattr(element.metadata, 'category_depth', None)
    if level is not None:
        return level

    return 1

def _process_table_element_new(table_element: Table, core_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Processes a single table element by generating a summary with an LLM."""
    document_id = core_metadata.get('document_id')
    logging.info(f"Processing table on page {table_element.metadata.page_number} for document_id: {document_id}")
    
    table_html = getattr(table_element.metadata, 'text_as_html', '')
    if not table_html:
        logging.warning(f"Table element found on page {table_element.metadata.page_number} but no HTML representation available for doc id {document_id}.")
        text = table_element.text
        metadata = core_metadata.copy()
        metadata.update({
            "page_number": str(table_element.metadata.page_number or -1),
            "category": "Table",
        })
        return {"text": text, "metadata": metadata}

    prompt = f'''As a data analyst, analyze the following table from a research paper, presented in HTML format.
Provide a concise, natural language summary of the table. Your summary should explain:
1. The main purpose of the table (what is it comparing or showing?).
2. The key findings, trends, or significant data points.
3. The relationships between the columns.

Your summary will be used for semantic search, so make it informative and self-contained.

Table HTML:
---
{table_html}
---

Summary:'''
    
    try:
        summary_text = get_llm_response(prompt, use_reasoner=False)
        
        chunk_metadata = core_metadata.copy()
        chunk_metadata.update({
            "page_number": str(table_element.metadata.page_number or -1),
            "category": "TableSummary",
            "original_table_html": table_html
        })
        
        return {"text": summary_text, "metadata": chunk_metadata}
    except Exception as e:
        logging.error(f"Failed to generate summary for table for doc id {document_id}: {e}")
        text = table_element.text
        metadata = core_metadata.copy()
        metadata.update({
            "page_number": str(table_element.metadata.page_number or -1),
            "category": "Table",
        })
        return {"text": text, "metadata": metadata}

def _process_unstructured_file_new(
    elements: List[Element], 
    core_metadata: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any] | None, List[Dict[str, Any]]]:
    """
    The new, advanced processing pipeline for unstructured files.
    Implements filtering, hierarchical splitting, and table summarization.
    """
    document_id = core_metadata.get('document_id')
    logging.info(f"Starting new advanced processing for unstructured file (doc id: {document_id})...")
    
    core_elements = _filter_elements(elements)
    
    all_chunks = []
    full_text_parts = []

    text_elements = []
    for el in core_elements:
        if isinstance(el, Table):
            table_chunk = _process_table_element_new(el, core_metadata)
            all_chunks.append(table_chunk)
            if 'text' in table_chunk:
                full_text_parts.append(table_chunk['text'])
        else:
            text_elements.append(el)

    title_path_stack: List[Tuple[int, str]] = []
    current_texts: List[str] = []
    current_page = 1

    text_splitter = NLTKTextSplitter(
        chunk_size=settings.PROCESSOR_CHUNK_SIZE,
        chunk_overlap=settings.PROCESSOR_CHUNK_OVERLAP,
    )

    def create_chunk_from_stack(page_num: int):
        if not current_texts:
            return

        text_block = "\n\n".join(current_texts).strip()
        if not text_block:
            current_texts.clear()
            return
        
        metadata = core_metadata.copy()
        for i, (level, title) in enumerate(title_path_stack):
            metadata[f"title_h{i+1}"] = title
        metadata["page_number"] = str(page_num)
        metadata["category"] = "NarrativeText"

        if len(text_block) > text_splitter._chunk_size:
            section_title = title_path_stack[-1][1] if title_path_stack else 'Root'
            logging.info(f"Chunk for section '{section_title}' is too long ({len(text_block)} chars), splitting...")
            sub_chunks = text_splitter.split_text(text_block)
            for i, sub_chunk_text in enumerate(sub_chunks):
                sub_chunk_metadata = metadata.copy()
                sub_chunk_metadata['sub_chunk_index'] = i
                all_chunks.append({"text": sub_chunk_text, "metadata": sub_chunk_metadata})
                full_text_parts.append(sub_chunk_text)
        else:
            all_chunks.append({"text": text_block, "metadata": metadata})
            full_text_parts.append(text_block)
        
        current_texts.clear()

    for element in text_elements:
        current_page = element.metadata.page_number or current_page
        
        if isinstance(element, Title):
            # Heuristic to ignore titles that are likely table/figure captions
            if re.match(r'^(table|figure|fig)\.?\s+\d+', element.text.strip(), re.IGNORECASE):
                current_texts.append(element.text.strip())
                continue

            # Ignore titles that indicate references/acknowledgments/bibliography
            if re.match(r'^(references?|bibliography|acknowledgements?|acknowledgments?)\b', element.text.strip(), re.IGNORECASE):
                # Do not treat as a section title; skip content accumulation
                continue

            # Ignore lines that look like DOI or URL-only titles
            if re.search(r'https?://doi\.org/\S+|\bdoi:\s*10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', element.text.strip(), re.IGNORECASE):
                # Keep as plain text to preserve context if needed, but avoid title_h*
                current_texts.append(element.text.strip())
                continue

            level = _get_title_level(element)
            
            while title_path_stack and title_path_stack[-1][0] >= level:
                create_chunk_from_stack(current_page)
                title_path_stack.pop()
            
            create_chunk_from_stack(current_page)

            title_path_stack.append((level, element.text.strip()))
        elif element.text and element.text.strip():
            current_texts.append(element.text.strip())

    create_chunk_from_stack(current_page)

    full_summary_dict = None
    if full_text_parts:
        try:
            full_text = "\n\n".join(full_text_parts)
            if full_text.strip():
                full_summary_dict = _generate_summary(full_text, core_metadata, "full")
        except Exception as e:
            logging.error(f"Failed to generate full document summary for doc id {document_id}: {e}")

    logging.info(f"New processing finished for doc id {document_id}. Generated {len(all_chunks)} chunks.")
    return all_chunks, full_summary_dict, []

# --- NEW FUNCTIONS END HERE ---

def _process_tabular_file(df: pd.DataFrame, core_metadata: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any] | None, List[Dict[str, Any]]]:
    """
    Converts a pandas DataFrame into chunks, using a base metadata dictionary.
    For wide tables, it also generates a markdown representation.
    """
    chunks = []
    df = df.reset_index(drop=True)

    # Generate markdown for wide tables
    if len(df.columns) > settings.PROCESSOR_WIDE_TABLE_THRESHOLD:
        md_chunk_metadata = core_metadata.copy()
        md_chunk_metadata.update({
            "page_number": "1",
            "category": "TabularMarkdown"
        })
        chunks.append({
            "text": f"Markdown representation of a wide table:\
\
{df.to_markdown(index=False)}",
            "metadata": md_chunk_metadata
        })

    for index, row in df.iterrows():
        int_index = cast(int, index)
        current_row_index = int_index + 2
        row_description = f"Row {current_row_index} contains: " + "; ".join([f"'{col}' is '{val}'" for col, val in row.items() if pd.notna(val)]) + "."
        
        chunk_metadata = core_metadata.copy()
        chunk_metadata.update({
            "page_number": "1",
            "row_index": str(current_row_index),
            "category": "TabularRow"
        })
        chunks.append({
            "text": row_description,
            "metadata": chunk_metadata
        })

    summary_dict = None
    try:
        stats_summary = df.describe(include='all').to_string()
        summary_text = f"Statistical summary:\n\n{stats_summary}"
        
        summary_metadata = core_metadata.copy()
        summary_metadata.update({
            "page_number": "-1",
            "is_summary": True,
            "summary_type": "full"
        })
        summary_dict = {"text": summary_text, "metadata": summary_metadata}
    except Exception as e:
        document_id = core_metadata.get("document_id", -1)
        logging.warning(f"Could not generate statistical summary for document_id {document_id}. Error: {e}")

    return chunks, summary_dict, []


def process_document(db: Session, file_path: Path, file_size: int, file_hash: str) -> Tuple[int, List[Dict[str, Any]], Dict[str, Any] | None, List[Dict[str, Any]]]:
    """
    The main document processing pipeline.
    """
    file_name = file_path.name
    file_type = file_path.suffix
    db_document = None

    try:
        # 1. Create initial document record
        logging.info(f"Creating database record for: {file_name}")
        db_document = Document(
            file_name=file_name,
            file_type=file_type,
            file_path=str(file_path.resolve()),
            file_hash=file_hash,
            file_size=file_size,
            status="processing"
        )
        db.add(db_document)
        db.commit()
        db.refresh(db_document)
        # Ensure we get the actual integer value, not a Column object
        document_id: int = getattr(db_document, 'id')

        # 2. Partition file
        logging.info(f"Partitioning document_id: {document_id}...")
        with tempfile.TemporaryDirectory() as temp_dir:
            elements = partition(
                filename=str(file_path),
                strategy="hi_res",
                languages=['eng'],
                include_page_breaks=True,
                pdf_image_output_dir_path=temp_dir,
                infer_table_structure=True
            )

        # 3. Extract and store core metadata
        try:
            _extract_and_store_metadata(db, document_id, elements)
            db.commit()
        except Exception as e:
            logging.error(f"Core metadata extraction failed for document_id {document_id}. Proceeding. Error: {e}")
            db.rollback()

        # 4. Fetch core metadata
        core_metadata = _get_metadata_as_dict(db, document_id)

        # 5. Process file content
        if file_type in ['.csv', '.xls', '.xlsx']:
            logging.info(f"Starting tabular data processing for document_id: {document_id}...")
            df = pd.read_csv(file_path) if file_type == '.csv' else pd.read_excel(file_path)
            chunks, summary, chapter_summaries = _process_tabular_file(df, core_metadata)
            logging.info(f"Processed tabular file into {len(chunks)} chunks.")
        else:
            # --- New advanced processing for unstructured files ---
            logging.info(f"Starting new advanced unstructured data processing for document_id: {document_id}...")
            chunks, summary, chapter_summaries = _process_unstructured_file_new(elements, core_metadata)
        
        # 6. Finalize document status
        setattr(db_document, 'status', "completed")
        db.commit()

        return document_id, chunks, summary, chapter_summaries

    except Exception as e:
        logging.error(f"Error processing document {file_path}: {e}", exc_info=True)
        if db_document:
            setattr(db_document, 'status', "failed")
            # Try to persist a readable error message into metadata for UI display
            try:
                db.add(DocumentMetadata(document_id=getattr(db_document, 'id'), key="error_message", value=str(e)))
            except Exception:
                # Ignore metadata write failures
                pass
            db.commit()
            return getattr(db_document, 'id'), [], None, []
        return -1, [], None, []


def reprocess_document(db: Session, document_id: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any] | None, List[Dict[str, Any]]]:
    """
    Reprocess an existing document record. This refreshes its metadata, rebuilds chunks/summaries,
    and updates the document status without creating a new database record.

    Returns: (chunks, full_summary, chapter_summaries)
    """
    try:
        db_document = db.query(Document).filter(Document.id == document_id).first()
        if not db_document:
            raise ValueError(f"Document with ID {document_id} not found.")

        file_path = Path(str(getattr(db_document, 'file_path')))
        file_type = file_path.suffix.lower()
        if not file_path.exists():
            setattr(db_document, 'status', "failed")
            db.commit()
            raise FileNotFoundError(f"Source file not found at path: {file_path}")

        # Mark as processing
        setattr(db_document, 'status', "processing")
        db.commit()

        # Partition file
        logging.info(f"Reprocessing document_id: {document_id} from {file_path}...")
        with tempfile.TemporaryDirectory() as temp_dir:
            elements = partition(
                filename=str(file_path),
                strategy="hi_res",
                languages=['eng'],
                include_page_breaks=True,
                pdf_image_output_dir_path=temp_dir,
                infer_table_structure=True
            )

        # Clear existing metadata to avoid duplication, then extract and store fresh metadata
        try:
            db.query(DocumentMetadata).filter(DocumentMetadata.document_id == document_id).delete(synchronize_session=False)
            db.commit()
            _extract_and_store_metadata(db, document_id, elements)
            db.commit()
        except Exception as e:
            logging.error(f"Metadata refresh failed for document_id {document_id}. Proceeding. Error: {e}")
            db.rollback()

        # Fetch core metadata for chunking
        core_metadata = _get_metadata_as_dict(db, document_id)

        # Process content into chunks/summaries
        if file_type in ['.csv', '.xls', '.xlsx']:
            logging.info(f"Reprocessing tabular data for document_id: {document_id}...")
            df = pd.read_csv(file_path) if file_type == '.csv' else pd.read_excel(file_path)
            chunks, summary, chapter_summaries = _process_tabular_file(df, core_metadata)
        else:
            logging.info(f"Reprocessing unstructured data for document_id: {document_id}...")
            chunks, summary, chapter_summaries = _process_unstructured_file_new(elements, core_metadata)

        # Mark as completed
        setattr(db_document, 'status', "completed")
        db.commit()

        return chunks, summary, chapter_summaries

    except Exception as e:
        logging.error(f"Error during reprocessing of document_id {document_id}: {e}", exc_info=True)
        try:
            db_document = db.query(Document).filter(Document.id == document_id).first()
            if db_document:
                setattr(db_document, 'status', "failed")
                # Persist error message for UI display
                try:
                    db.add(DocumentMetadata(document_id=document_id, key="error_message", value=str(e)))
                except Exception:
                    pass
                db.commit()
        except Exception:
            pass
        return [], None, []
