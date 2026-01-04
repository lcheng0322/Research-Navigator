import time
import logging
from typing import List, Optional
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError
from openai.types.chat import ChatCompletionMessageParam
from ..core.config import settings

# --- Initialize LLM Clients ---
# The configuration is now loaded centrally from the settings object in core/config.py
reasoner_client = None
chat_client = None
reasoner_model_name = None
chat_model_name = None

# Initialize DeepSeek clients
api_key = settings.DEEPSEEK_API_KEY
if not api_key or "YOUR_DEEPSEEK_API_KEY" in api_key:
    print("WARNING: DEEPSEEK_API_KEY not found or not set. DeepSeek calls will fail.")
else:
    reasoner_client = OpenAI(api_key=api_key, base_url=settings.DEEPSEEK_BASE_URL)
    chat_client = OpenAI(api_key=api_key, base_url=settings.DEEPSEEK_BASE_URL)
    reasoner_model_name = settings.DEEPSEEK_REASONER_MODEL_NAME
    chat_model_name = settings.DEEPSEEK_CHAT_MODEL_NAME
    print(f"LLM Service configured for DeepSeek using model {reasoner_model_name} for reasoning and {chat_model_name} for chat.")


def get_llm_response(prompt: str, json_mode: bool = False, retries: int = 3, initial_delay: float = 1.0, use_reasoner: bool = False) -> str:
    """
    Sends a prompt to the configured LLM and gets a response, with error handling and retries.

    Args:
        prompt: The prompt to send to the LLM.
        json_mode: If True, requests the LLM to return a JSON object.
        retries: The maximum number of times to retry the request.
        initial_delay: The initial delay in seconds for exponential backoff.
        use_reasoner: If True, uses the reasoning model (deepseek-reasoner), otherwise uses the chat model (deepseek-chat)

    Returns:
        The LLM's response as a string.
    """
    if use_reasoner:
        client = reasoner_client
        model_name = reasoner_model_name
        model_type = "reasoner"
    else:
        client = chat_client
        model_name = chat_model_name
        model_type = "chat"
    
    if not client or not model_name:
        logging.error(f"LLM client for {model_type} model is not initialized. Please check your API key and configuration.")
        raise ValueError(f"LLM client for {model_type} model is not initialized.")

    messages: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": "You are a helpful research assistant."},
        {"role": "user", "content": prompt},
    ]
    temperature = 0.1
    
    request_params: dict = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        request_params["response_format"] = {"type": "json_object"}

    for attempt in range(retries):
        try:
            logging.info(f"Sending prompt to DeepSeek {model_type} model ({model_name}), attempt {attempt + 1}/{retries}...")
            
            response = client.chat.completions.create(**request_params)
            
            if response.choices:
                return response.choices[0].message.content or ""
            
            logging.warning("LLM response was empty.")
            return "No response from LLM."

        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            delay = initial_delay * (2 ** attempt)
            logging.warning(f"Retryable LLM API error: {e}. Retrying in {delay:.2f} seconds...")
            if attempt == retries - 1:
                logging.error(f"LLM call failed after {retries} attempts. Final error: {e}")
                raise
            time.sleep(delay)
            
        except Exception as e:
            logging.error(f"An unexpected, non-retryable error occurred while calling the LLM: {e}", exc_info=True)
            raise  

    raise Exception(f"LLM call failed after {retries} attempts.")