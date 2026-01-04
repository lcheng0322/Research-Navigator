import { useEffect, useRef } from 'react';
import { MessagePlugin } from 'tdesign-react';
import apiClient from '../services/api';
import useTaskStore, { type TaskRecord, type TaskStatus } from '../store/taskStore';

interface UseTaskPollingOptions {
  taskId: string | null;
  taskType: string;
  title?: string;
  immediate?: boolean;
  pollIntervalMs?: number;
  onTaskSuccess?: (result: any) => void;
  onTaskFailure?: (result: any) => void;
}

const defaultIntervalMs = 3000;

const useTaskPolling = ({
  taskId,
  taskType,
  title,
  immediate = false,
  pollIntervalMs = defaultIntervalMs,
  onTaskSuccess,
  onTaskFailure,
}: UseTaskPollingOptions) => {
  const pollingRef = useRef<number | null>(null);
  const { setTask, updateTask, getTaskById } = useTaskStore();

  useEffect(() => {
    if (!taskId) {
      return undefined;
    }

    const stopPolling = () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };

    const executePoll = async () => {
      try {
        const response = await apiClient.get(`/tasks/${taskId}`);
        console.log('Task polling response:', response.data);
        const { status, result } = response.data as { task_id: string; status: TaskStatus; result: any };
        console.log('Extracted status:', status, 'result:', result);
        updateTask(taskId, { status, result });

        if (status === 'SUCCESS') {
          if (onTaskSuccess) {
            onTaskSuccess(result);
          } else {
            // 只有当没有自定义成功回调时才显示默认消息
            MessagePlugin.success(`${title ?? taskType} 完成`);
          }
          stopPolling();
        } else if (status === 'FAILURE') {
          if (onTaskFailure) {
            onTaskFailure(result);
          }
          MessagePlugin.error(`${title ?? taskType} 失败`);
          updateTask(taskId, { error: typeof result === 'string' ? result : JSON.stringify(result) });
          stopPolling();
        }
      } catch (error) {
        console.error('Task polling failed:', error);
        MessagePlugin.error('获取任务状态失败');
        stopPolling();
      }
    };

    const startPolling = () => {
      executePoll();
      pollingRef.current = window.setInterval(executePoll, pollIntervalMs);
    };

    const existingTask = getTaskById(taskId);
    if (!existingTask) {
      const now = new Date().toISOString();
      const newTask: TaskRecord = {
        taskId,
        type: taskType,
        title: title ?? `${taskType} Task`,
        status: 'PENDING',
        createdAt: now,
        updatedAt: now,
      };
      setTask(newTask);
    } else if (existingTask.status === 'SUCCESS' || existingTask.status === 'FAILURE') {
      if (existingTask.status === 'SUCCESS' && onTaskSuccess) {
        onTaskSuccess(existingTask.result);
      }
      if (existingTask.status === 'FAILURE' && onTaskFailure) {
        onTaskFailure(existingTask.result);
      }
      return undefined;
    }

    if (immediate) {
      startPolling();
    } else {
      executePoll();
    }

    return () => {
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, taskType, title, pollIntervalMs, onTaskSuccess, onTaskFailure, immediate, setTask, updateTask, getTaskById]);
};

export default useTaskPolling;
