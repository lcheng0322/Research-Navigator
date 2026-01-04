import { useEffect } from 'react';
import useTaskStore, { type TaskRecord, type TaskStatus } from '../store/taskStore';
import useAuthStore from '../store/authStore';
import apiClient from '../services/api';

interface UseTaskStreamOptions {
  taskId: string | null;
  taskType: string;
  title?: string;
  immediate?: boolean;
  onTaskSuccess?: (result: any) => void;
  onTaskFailure?: (result: any) => void;
}

const useTaskStream = ({
  taskId,
  taskType,
  title,
  immediate = true,
  onTaskSuccess,
  onTaskFailure,
}: UseTaskStreamOptions) => {
  const { setTask, updateTask, getTaskById } = useTaskStore();
  const token = useAuthStore.getState().token;

  useEffect(() => {
    if (!taskId || !immediate) return;

    if (!token || token.trim().length === 0) {
      console.error('[useTaskStream] Auth token missing, skipping WebSocket connection');
      // 标记任务错误，提示用户重新登录
      updateTask(taskId, { error: '缺少认证令牌，请重新登录后重试。' });
      return;
    }

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
    }

    // 动态构造 WebSocket 地址：
    // - 复用 axios 的 baseURL 作为单一事实来源
    // - http -> ws, https -> wss，以适配本地与生产环境
    // - 路径固定为 /api/tasks/ws/{task_id}
    let wsUrl = '';
    try {
      const base = new URL(apiClient.defaults.baseURL ?? window.location.origin);
      const wsProtocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsOrigin = `${wsProtocol}//${base.host}`; // e.g. ws://127.0.0.1:8000 或 wss://api.example.com
      wsUrl = `${wsOrigin}/api/tasks/ws/${taskId}?token=${encodeURIComponent(token ?? '')}`;
    } catch (e) {
      // 兜底：如果 URL 解析失败，回退到本地开发默认地址
      wsUrl = `ws://127.0.0.1:8000/api/tasks/ws/${taskId}?token=${encodeURIComponent(token ?? '')}`;
    }
    console.info('[useTaskStream] Connecting to WebSocket:', wsUrl);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.info('[useTaskStream] WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as { task_id: string; status: TaskStatus; result: any };
        updateTask(taskId, { status: data.status, result: data.result });
        if (data.status === 'SUCCESS') {
          if (onTaskSuccess) onTaskSuccess(data.result);
          ws.close();
        }
        if (data.status === 'FAILURE') {
          if (onTaskFailure) onTaskFailure(data.result);
          updateTask(taskId, { error: typeof data.result === 'string' ? data.result : JSON.stringify(data.result) });
          ws.close();
        }
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };

    ws.onerror = (e) => {
      console.error('WebSocket error:', e);
      // 尝试回退检查任务 HTTP 状态，帮助定位后端是否可达/任务是否存在
      (async () => {
        try {
          const resp = await apiClient.get(`/tasks/${taskId}`);
          console.info('[useTaskStream] Fallback HTTP task check:', resp.data);
        } catch (httpErr) {
          console.warn('[useTaskStream] Fallback HTTP task check failed:', httpErr);
        }
      })();
      try { ws.close(); } catch (_) { /* noop */ }
    };

    ws.onclose = (event) => {
      console.warn('[useTaskStream] WebSocket closed:', { code: event.code, reason: event.reason });
      // 1008 通常表示策略违规（例如鉴权失败/令牌问题）
      if (event.code === 1008) {
        updateTask(taskId, { error: 'WebSocket 鉴权失败，请重新登录后重试。' });
      }
    };

    return () => {
      try { ws.close(); } catch (_) { /* noop */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, taskType, title, immediate]);
};

export default useTaskStream;