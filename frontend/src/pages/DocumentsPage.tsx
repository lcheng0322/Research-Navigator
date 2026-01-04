import { useState, useEffect } from 'react';
import {
  Table,
  Loading,
  Alert,
  Button,
  Dialog,
  Upload,
  MessagePlugin,
  Tag,
  Tooltip,
  Space,
  Card,
} from 'tdesign-react';
import type { UploadFile, RequestMethodResponse, TableProps } from 'tdesign-react';
import { UploadIcon, DeleteIcon, BrowseIcon, RefreshIcon, CaretRightSmallIcon } from 'tdesign-icons-react';
import ReactMarkdown from 'react-markdown';
import apiClient from '../services/api';
import useTaskStore from '../store/taskStore';
import useTaskStream from '../hooks/useTaskStream';
import { useShallow } from 'zustand/react/shallow';

interface Document {
  id: number;
  file_name: string;
  status: string;
  error_message?: string;
  metadata: {
    [key: string]: any;
  };
}

const getStatusTheme = (status: string) => {
  switch (status) {
    case 'completed': return 'success';
    case 'processing': return 'warning';
    case 'failed': return 'danger';
    default: return 'primary';
  }
};

const DocumentsPage = () => {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isUploadVisible, setIsUploadVisible] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<Document | null>(null);
  const [viewingDoc, setViewingDoc] = useState<Document | null>(null);
  const [docContent, setDocContent] = useState<string>('');
  const [isContentLoading, setIsContentLoading] = useState(false);
  const [expandedRowKeys, setExpandedRowKeys] = useState<number[]>([]);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [currentTaskTitle, setCurrentTaskTitle] = useState<string | null>(null);

  const setTask = useTaskStore((state) => state.setTask);
  const ingestionTasks = useTaskStore(
    useShallow((state) => state.tasks.filter((t) => t.type === 'document-ingestion'))
  );

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get('/documents/');
      setDocuments(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to fetch documents. Please try again later.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  // Stream updates for the latest ingestion task (WebSocket), and refresh documents on success
  useTaskStream({
    taskId: currentTaskId,
    taskType: 'document-ingestion',
    title: currentTaskTitle ?? undefined,
    immediate: true,
    onTaskSuccess: () => {
      MessagePlugin.success('Document ingestion completed.');
      fetchDocuments();
    },
    onTaskFailure: () => {
      MessagePlugin.error('Document ingestion failed.');
    },
  });

  const handleDelete = async () => {
    if (!deleteConfirm) return;
    try {
      await apiClient.delete(`/documents/${deleteConfirm.id}`);
      MessagePlugin.success(`Successfully deleted ${deleteConfirm.file_name}.`);
      setDeleteConfirm(null);
      fetchDocuments();
    } catch (err) {
      MessagePlugin.error('Failed to delete document.');
    }
  };

  const handleReprocess = async (docId: number) => {
    try {
      await apiClient.post(`/documents/${docId}/reprocess`);
      MessagePlugin.success('Reprocessing started.');
      fetchDocuments();
    } catch (err) {
      MessagePlugin.error('Failed to start reprocessing.');
    }
  };

  const handleViewContent = async (doc: Document) => {
    setViewingDoc(doc);
    setIsContentLoading(true);
    try {
      const response = await apiClient.get(`/documents/${doc.id}/content`);
      const content = response.data.map((chunk: any) => chunk.text).join('\n\n---\n\n');
      setDocContent(content);
    } catch (err) {
      setDocContent('Failed to load document content.');
    } finally {
      setIsContentLoading(false);
    }
  };

  const customUploadRequest = (files: UploadFile | UploadFile[]): Promise<RequestMethodResponse> => {
    const file = Array.isArray(files) ? files[0] : files;
    return new Promise((resolve) => {
      if (!file?.raw) {
        return resolve({ status: 'fail', error: 'File is missing.', response: {} });
      }
      const formData = new FormData();
      formData.append('file', file.raw);
      apiClient.post('/upload/', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
        .then(response => {
          const data = response.data || {};
          if (data.task_id) {
            // Async ingestion task
            const now = new Date().toISOString();
            const title = `Ingest: ${file.name}`;
            setTask({
              taskId: data.task_id,
              type: 'document-ingestion',
              title,
              status: 'PENDING',
              createdAt: now,
              updatedAt: now,
              parameters: { fileName: file.name },
            });
            setCurrentTaskId(data.task_id);
            setCurrentTaskTitle(title);
            MessagePlugin.success('File uploaded! Ingestion task started.');
          } else {
            // Analysis-only or legacy sync path
            MessagePlugin.success('File processed successfully.');
            // For analysis-only, no document list refresh is needed
          }
          setIsUploadVisible(false);
          resolve({ status: 'success', response });
        })
        .catch(err => {
          MessagePlugin.error(err.response?.data?.detail || 'Upload failed.');
          resolve({ status: 'fail', error: err, response: err.response });
        });
    });
  };

  const columns: TableProps<Document>['columns'] = [
    { colKey: 'metadata.title', title: 'Title', ellipsis: true, cell: ({ row }) => row.metadata?.title || 'N/A' },
    { colKey: 'metadata.authors', title: 'Authors', ellipsis: true, cell: ({ row }) => (Array.isArray(row.metadata?.authors) ? row.metadata.authors.join(', ') : row.metadata?.authors) || 'N/A' },
    { colKey: 'metadata.publication_year', title: 'Year', cell: ({ row }) => row.metadata?.publication_year || 'N/A' },
    {
      colKey: 'status',
      title: 'Status',
      cell: ({ row }) => (
        <Tag theme={getStatusTheme(row.status)}>{row.status}</Tag>
      ),
    },
    { colKey: 'file_name', title: 'File Name', ellipsis: true },
    {
      colKey: 'actions',
      title: 'Actions',
      cell: ({ row }) => (
        <Space>
          <Tooltip content="View Content"><Button theme="primary" variant="text" icon={<BrowseIcon />} onClick={() => handleViewContent(row)} /></Tooltip>
          {row.status === 'failed' && <Tooltip content="Reprocess"><Button theme="primary" variant="text" icon={<RefreshIcon />} onClick={() => handleReprocess(row.id)} /></Tooltip>}
          <Tooltip content="Delete"><Button theme="danger" variant="text" icon={<DeleteIcon />} onClick={() => setDeleteConfirm(row)} /></Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">Document Management</h1>
        <p className="page-subtitle">Upload, view, and manage your research documents.</p>
      </div>

      {/* Ingestion Task Status (Latest Task Only) */}
      {currentTaskId && (
        <Card style={{ marginBottom: '16px' }} title="Latest Ingestion Task">
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {(() => {
              const latest = ingestionTasks.find((t) => t.taskId === currentTaskId);
              return latest ? (
                <div style={{ border: '1px solid var(--component-border)', borderRadius: 6, padding: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                      <strong>{latest.title}</strong>
                      <Tag theme={latest.status === 'SUCCESS' ? 'success' : latest.status === 'FAILURE' ? 'danger' : latest.status === 'STARTED' ? 'primary' : 'warning'}>{latest.status}</Tag>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Task ID: {latest.taskId}</div>
                  </div>
                  {(latest.status === 'PENDING' || latest.status === 'STARTED') && <Loading text="Processing..." />}
                  {latest.status === 'SUCCESS' && (
                    <Alert theme="success" title="Ingestion Complete" message="Document ingestion finished successfully." />
                  )}
                  {latest.status === 'FAILURE' && (
                    <Alert theme="error" title="Ingestion Failed" message={String(latest.error || 'Task failed.')} />
                  )}
                </div>
              ) : (
                <Alert theme="info" title="No active ingestion task" />
              );
            })()}
          </div>
        </Card>
      )}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '16px' }}>
          <Button icon={<UploadIcon />} onClick={() => setIsUploadVisible(true)}>Upload File</Button>
        </div>
        {loading && <Loading text="Loading documents..." />}
        {error && <Alert theme="error" title="Error" message={error} />}
        {!loading && !error && (
          <div style={{ overflowX: 'auto' }}>
            <Table
              rowKey="id"
              data={documents}
              columns={columns}
              empty="No documents found."
              bordered
              stripe
              expandedRowKeys={expandedRowKeys}
              onExpandChange={(keys) => setExpandedRowKeys(keys as number[])}
              expandedRow={({ row }) =>
                row.status === 'failed' && row.error_message ? (
                  <div style={{ padding: '10px', backgroundColor: '#fff1f0' }}>
                    <strong>Error Details:</strong>
                    <pre style={{ whiteSpace: 'pre-wrap', marginTop: '5px' }}>{row.error_message}</pre>
                  </div>
                ) : null
              }
              expandIcon={({ expanded, onExpand, row }: any) => 
                row.status === 'failed' ? (
                  <CaretRightSmallIcon 
                    size="16px" 
                    className={`t-table__expand-icon ${expanded ? 't-table__expand-icon-expanded' : ''}`} 
                    onClick={(e) => onExpand(e)} 
                  />
                ) : null
              }
            />
          </div>
        )}
      </Card>
      <Dialog header="Upload New Document" visible={isUploadVisible} onClose={() => setIsUploadVisible(false)} footer={false}>
        <Upload requestMethod={customUploadRequest} accept=".pdf,.doc,.docx,.md,.csv,.xls,.xlsx" multiple={false} />
      </Dialog>
      <Dialog header="Confirm Deletion" visible={!!deleteConfirm} onConfirm={handleDelete} onClose={() => setDeleteConfirm(null)}>
        <p>Are you sure you want to delete <strong>{deleteConfirm?.file_name}</strong>? This action cannot be undone.</p>
      </Dialog>
      <Dialog header={`Content: ${viewingDoc?.file_name}`} visible={!!viewingDoc} onClose={() => setViewingDoc(null)} width="80%">
        {isContentLoading ? <Loading /> : <div style={{ maxHeight: '70vh', overflowY: 'auto' }}><ReactMarkdown>{docContent}</ReactMarkdown></div>}
      </Dialog>
    </div>
  );
};

export default DocumentsPage;
