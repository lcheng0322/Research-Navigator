import { useEffect, useState } from 'react';
import { Loading, Alert } from 'tdesign-react';
import apiClient from '../services/api';
import useTaskStore from '../store/taskStore';

interface TaskWatcherProps {
  taskId: string;
  onSuccess: (result: any) => React.ReactNode;
  onFailure: (error: string) => React.ReactNode;
  onPending: () => React.ReactNode;
  onStarted: () => React.ReactNode;
}

const TaskWatcher = ({ taskId, onSuccess, onFailure, onPending, onStarted }: TaskWatcherProps) => {
  const [error, setError] = useState<string | null>(null);
  const task = useTaskStore((state) => state.tasks.find((t) => t.taskId === taskId));
  const setTask = useTaskStore((state) => state.setTask);

  useEffect(() => {
    const fetchTask = async () => {
      try {
        const response = await apiClient.get(`/tasks/${taskId}`);
        setTask(response.data);
      } catch (err) {
        setError('Failed to fetch task details');
        console.error(err);
      }
    };

    if (!task) {
      fetchTask();
    }

    if (task && (task.status === 'PENDING' || task.status === 'STARTED')) {
      const interval = setInterval(async () => {
        try {
          const response = await apiClient.get(`/tasks/${taskId}`);
          setTask(response.data);
          if (response.data.status === 'SUCCESS' || response.data.status === 'FAILURE') {
            clearInterval(interval);
          }
        } catch (err) {
          console.error('Failed to poll task status:', err);
        }
      }, 5000); // Poll every 5 seconds

      return () => clearInterval(interval);
    }
  }, [taskId, task, setTask]);

  if (error) {
    return <Alert theme="error" message={error} />;
  }

  if (!task) {
    return <Loading size="large" />;
  }

  switch (task.status) {
    case 'SUCCESS':
      return <>{onSuccess(task.result)}</>;
    case 'FAILURE':
      return <>{onFailure(task.error || 'Unknown error')}</>;
    case 'STARTED':
        return <>{onStarted()}</>;
    case 'PENDING':
    default:
      return <>{onPending()}</>;
  }
};

export default TaskWatcher;
