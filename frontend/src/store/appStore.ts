import { create } from 'zustand';

interface AppState {
  isLoading: boolean;
  setLoading: (isLoading: boolean) => void;
}

const useAppStore = create<AppState>()((set) => ({
  isLoading: false,
  setLoading: (isLoading) => set({ isLoading }),
}));

export default useAppStore;
