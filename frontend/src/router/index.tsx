import { useRoutes, Navigate } from 'react-router-dom';
import LoginPage from '../pages/LoginPage';
import RegisterPage from '../pages/RegisterPage';
import MainLayout from '../layouts/MainLayout';
import DashboardPage from '../pages/DashboardPage';
import DocumentsPage from '../pages/DocumentsPage';
import QueryPage from '../pages/QueryPage';
import LiteratureReviewPage from '../pages/LiteratureReviewPage';
import GapAnalysisPage from '../pages/GapAnalysisPage';
import TabularDataAnalysisPage from '../pages/TabularDataAnalysisPage';
import ExperimentDesignPage from '../pages/ExperimentDesignPage';
import TaskCenterPage from '../pages/TaskCenterPage';
import ResultViewerPage from '../pages/ResultViewerPage';
import ProtectedRoute from './ProtectedRoute';



const AppRouter = () => {
  const routes = useRoutes([
    {
      path: '/login',
      element: <LoginPage />,
    },
    {
      path: '/register',
      element: <RegisterPage />,
    },
    {
      path: '/',
      element: <ProtectedRoute />,
      children: [
        {
          element: <MainLayout />,
          children: [
            { index: true, element: <Navigate to="/dashboard" replace /> },
            { path: 'dashboard', element: <DashboardPage /> },
            { path: 'documents', element: <DocumentsPage /> },
            { path: 'query', element: <QueryPage /> },
            { path: 'literature-review', element: <LiteratureReviewPage /> },
            { path: 'gap-analysis', element: <GapAnalysisPage /> },
            { path: 'tabular-analysis', element: <TabularDataAnalysisPage /> },
            { path: 'experiment-design', element: <ExperimentDesignPage /> },
            { path: 'tasks', element: <TaskCenterPage /> },
            { path: 'results/:taskId', element: <ResultViewerPage /> },

          ],
        },
      ],
    },
  ]);

  return routes;
};

export default AppRouter;