import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type TaskStatus = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE' | 'RETRY' | string;

export interface TaskRecord {
  taskId: string;
  type: string;
  title: string;
  status: TaskStatus;
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
  result?: any;
  error?: string | null;
  parameters?: Record<string, unknown>;
}

interface TaskState {
  tasks: TaskRecord[];
  setTask: (task: TaskRecord) => void;
  updateTask: (taskId: string, updates: Partial<TaskRecord>) => void;
  removeTask: (taskId: string) => void;
  clearCompletedTasks: () => void;
  getTaskById: (taskId: string) => TaskRecord | undefined;
}

export const isTaskTerminal = (status: TaskStatus) => status === 'SUCCESS' || status === 'FAILURE';

const useTaskStore = create<TaskState>()(
  persist(
    (set, get) => ({
      tasks: [],
      setTask: (task) => {
        set((state) => {
          const existingTaskIndex = state.tasks.findIndex((existing) => existing.taskId === task.taskId);
          if (existingTaskIndex >= 0) {
            const existingTask = state.tasks[existingTaskIndex];
            const mergedTask = {
              ...existingTask,
              ...task,
              updatedAt: task.updatedAt ?? existingTask.updatedAt,
            };
            const updatedTasks = [...state.tasks];
            updatedTasks[existingTaskIndex] = mergedTask;
            return { tasks: updatedTasks };
          }
          return { tasks: [task, ...state.tasks] };
        });
      },
      updateTask: (taskId, updates) => {
        set((state) => ({
          tasks: state.tasks.map((task) =>
            task.taskId === taskId
              ? {
                  ...task,
                  ...updates,
                  updatedAt: updates.updatedAt ?? new Date().toISOString(),
                  completedAt: updates.completedAt ?? (updates.status && isTaskTerminal(updates.status) ? new Date().toISOString() : task.completedAt),
                }
              : task
          ),
        }));
      },
      removeTask: (taskId) => {
        set((state) => ({ tasks: state.tasks.filter((task) => task.taskId !== taskId) }));
      },
      clearCompletedTasks: () => {
        set((state) => ({ tasks: state.tasks.filter((task) => !isTaskTerminal(task.status)) }));
      },
      getTaskById: (taskId) => get().tasks.find((task) => task.taskId === taskId),
    }),
    {
      name: 'task-center-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ tasks: state.tasks }),
    }
  )
);

export default useTaskStore;
