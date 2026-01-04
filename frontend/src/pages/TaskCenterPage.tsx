import { useMemo, useState, useEffect } from 'react';
import { Card, Table, Tag, Button, Empty, Tooltip, Popconfirm, MessagePlugin, RadioGroup, Radio } from 'tdesign-react';
import type { TableProps } from 'tdesign-react';
import { KeyIcon, RefreshIcon, DeleteIcon } from 'tdesign-icons-react';
import { useNavigate } from 'react-router-dom';
import useTaskStore, { type TaskRecord, type TaskStatus, isTaskTerminal } from '../store/taskStore';
import apiClient from '../services/api';
import { saveAs } from 'file-saver';

const statusThemeMap: Record<TaskStatus, { theme: 'default' | 'primary' | 'success' | 'warning' | 'danger'; label: string }> = {
  PENDING: { theme: 'warning', label: 'Pending' },
  STARTED: { theme: 'primary', label: 'Running' },
  SUCCESS: { theme: 'success', label: 'Success' },
  FAILURE: { theme: 'danger', label: 'Failure' },
  RETRY: { theme: 'warning', label: 'Retrying' },
};

const getStatusTagProps = (status: TaskStatus) => {
  const defaultConfig = { theme: 'default' as const, label: status };
  return statusThemeMap[status] ?? defaultConfig;
};

const TaskCenterPage = () => {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'completed'>('all');
  const [typeFilter, setTypeFilter] = useState<'all' | 'document-ingestion' | 'literature-review' | 'gap-analysis'>('all');
  const allowedTypes = ['document-ingestion', 'literature-review', 'gap-analysis'] as const;
  const tasks = useTaskStore((state) => state.tasks);
  const removeTask = useTaskStore((state) => state.removeTask);
  const clearCompletedTasks = useTaskStore((state) => state.clearCompletedTasks);
  const updateTask = useTaskStore((state) => state.updateTask);

  useEffect(() => {
    const activeTasks = tasks.filter(task => !isTaskTerminal(task.status));
    if (activeTasks.length === 0) return;

    const pollInterval = setInterval(async () => {
      for (const task of activeTasks) {
        try {
          const response = await apiClient.get(`/tasks/${task.taskId}`);
          const { status, result } = response.data as { task_id: string; status: TaskStatus; result: any };
          if (status !== task.status) {
            updateTask(task.taskId, { status, result });
          }
        } catch (error) {
          console.error(`Failed to poll task ${task.taskId}:`, error);
        }
      }
    }, 5000);

    return () => clearInterval(pollInterval);
  }, [tasks, updateTask]);

  const filteredTasks = useMemo(() => {
    // Only show the three supported types in Task Center
    const visibleTasks = tasks.filter((task) => allowedTypes.includes(task.type as any));

    const byStatus = (() => {
      if (statusFilter === 'active') return visibleTasks.filter((task) => !isTaskTerminal(task.status));
      if (statusFilter === 'completed') return visibleTasks.filter((task) => isTaskTerminal(task.status));
      return visibleTasks;
    })();

    if (typeFilter === 'all') return byStatus;
    return byStatus.filter((task) => task.type === typeFilter);
  }, [statusFilter, typeFilter, tasks]);

  const handleRemoveTask = (taskId: string) => {
    removeTask(taskId);
    MessagePlugin.success('Removed task from local list.');
  };

  const handleClearCompleted = () => {
    clearCompletedTasks();
    MessagePlugin.success('Cleared completed tasks.');
  };

  const getDownloadEndpoint = (type: string, taskId: string): { url: string; filename: string } | null => {
    switch (type) {
      case 'literature-review':
        return { url: `/generate/literature-review/download/${taskId}`, filename: `literature_review_${taskId}.docx` };
      case 'gap-analysis':
        return { url: `/analyze/research-gaps/download/${taskId}`, filename: `gap_analysis_${taskId}.docx` };
      default:
        return null;
    }
  };

  const handleDownloadDocx = async (row: TaskRecord) => {
    const mapping = getDownloadEndpoint(row.type, row.taskId);
    if (!mapping) {
      MessagePlugin.warning('该任务类型暂不支持DOCX导出');
      return;
    }
    if (row.status !== 'SUCCESS') {
      MessagePlugin.warning('任务未完成，无法导出DOCX');
      return;
    }
    try {
      const response = await apiClient.get(mapping.url, { responseType: 'blob' });
      saveAs(response.data, mapping.filename);
      MessagePlugin.success('DOCX 下载成功');
    } catch (error) {
      console.error(error);
      MessagePlugin.error('DOCX 下载失败');
    }
  };

  const columns: TableProps<TaskRecord>['columns'] = [
    { colKey: 'title', title: 'Task', cell: ({ row }) => <div><strong>{row.title}</strong><span style={{ fontSize: 12, color: '#888', display: 'block' }}>{row.type}</span></div> },
    { colKey: 'status', title: 'Status', width: 120, cell: ({ row }) => { const { theme, label } = getStatusTagProps(row.status); return <Tag theme={theme} variant="light-outline">{label}</Tag>; } },
    { colKey: 'createdAt', title: 'Created At', width: 180, cell: ({ row }) => new Date(row.createdAt).toLocaleString() },
    { colKey: 'updatedAt', title: 'Updated At', width: 180, cell: ({ row }) => new Date(row.updatedAt).toLocaleString() },
    {
      colKey: 'actions',
      title: 'Actions',
      width: 260,
      cell: ({ row }) => (
        <div>
          <Tooltip content="View details"><Button size="small" variant="outline" icon={<KeyIcon />} disabled={!row.taskId} onClick={() => navigate(`/results/${row.taskId}`)} /></Tooltip>
          <Tooltip content="Poll now"><Button size="small" variant="outline" icon={<RefreshIcon />} disabled={!row.taskId} onClick={() => navigate(`/results/${row.taskId}?refresh=1`)} style={{marginLeft: '8px'}} /></Tooltip>
          <Tooltip content="Download DOCX"><Button size="small" theme="primary" variant="outline" disabled={!getDownloadEndpoint(row.type, row.taskId) || row.status !== 'SUCCESS'} onClick={() => handleDownloadDocx(row)} style={{marginLeft: '8px'}}>
            DOCX
          </Button></Tooltip>
          <Tooltip content="Remove from list"><Popconfirm content="Remove this task from local list?" onConfirm={() => handleRemoveTask(row.taskId)}><Button size="small" theme="danger" variant="outline" icon={<DeleteIcon />} style={{marginLeft: '8px'}} /></Popconfirm></Tooltip>
        </div>
      ),
    },
  ];

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">Task Center</h1>
        <p className="page-subtitle">Monitor and manage all your background tasks.</p>
      </div>

      <Card className="card">
        <div className="card-body">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--spacing-4)' }}>
              <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>Status</div>
                  <RadioGroup size="small" value={statusFilter} onChange={(value) => setStatusFilter(value as any)}>
                    <Radio value="all">All</Radio>
                    <Radio value="active">Active</Radio>
                    <Radio value="completed">Completed</Radio>
                  </RadioGroup>
                </div>
                <div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>Type</div>
                  <RadioGroup size="small" value={typeFilter} onChange={(value) => setTypeFilter(value as any)}>
                    <Radio value="all">All</Radio>
                    <Radio value="document-ingestion">Document Ingestion</Radio>
                    <Radio value="literature-review">Literature Review</Radio>
                    <Radio value="gap-analysis">Gap Analysis</Radio>
                  </RadioGroup>
                </div>
              </div>
              <Button
                theme="danger"
                variant="outline"
                className="btn btn-secondary"
                disabled={filteredTasks.length === 0 || filteredTasks.every((task) => !isTaskTerminal(task.status))}
                onClick={handleClearCompleted}
              >
                Clear Completed
              </Button>
            </div>
            {filteredTasks.length === 0 ? (
              <Empty description="No tasks yet. Start an analysis to see it here." />
            ) : (
              <Table
                rowKey="taskId"
                data={filteredTasks}
                columns={columns}
                pagination={{ pageSize: 10 }}
                bordered
                hover
              />
            )}
        </div>
      </Card>
    </div>
  );
};

export default TaskCenterPage;
