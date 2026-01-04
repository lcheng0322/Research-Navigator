import axios from 'axios';
import useAuthStore from '../store/authStore';
import useAppStore from '../store/appStore';

const apiClient = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',
});

apiClient.interceptors.request.use(
  (config) => {
    useAppStore.getState().setLoading(true);
    const token = useAuthStore.getState().token;
    if (!config.headers) {
      config.headers = {} as typeof config.headers;
    }

    if (!config.headers['Accept']) {
      config.headers['Accept'] = 'application/json';
    }

    if (token && !config.headers['Authorization']) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }

    return config;
  },
  (error) => {
    useAppStore.getState().setLoading(false);
    return Promise.reject(error);
  }
);

apiClient.interceptors.response.use(
  (response) => {
    useAppStore.getState().setLoading(false);
    return response;
  },
  (error) => {
    useAppStore.getState().setLoading(false);
    if (error.response?.status === 401) {
      const { logout } = useAuthStore.getState();
      logout();
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
