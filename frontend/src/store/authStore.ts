import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import apiClient from '../services/api';

interface User {
  id: number;
  email: string;
  is_active: boolean;
}

interface AuthState {
  token: string | null;
  user: User | null;
  setToken: (token: string) => void;
  fetchCurrentUser: () => Promise<void>;
  logout: () => void;
}

const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setToken: (token) => set({ token }),
      fetchCurrentUser: async () => {
        try {
          const response = await apiClient.get('/users/me');
          set({ user: response.data });
        } catch (error) {
          console.error('Failed to fetch current user:', error);
          set({ user: null });
        }
      },
      logout: () => set({ token: null, user: null }),
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ token: state.token }),
    }
  )
);

export default useAuthStore;
