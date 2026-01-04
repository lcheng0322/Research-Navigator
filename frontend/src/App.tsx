import AppRouter from './router';
import { Loading } from 'tdesign-react';
import useAppStore from './store/appStore';

function App() {
  const isLoading = useAppStore((state) => state.isLoading);

  return (
    <div className="app-container">
      {isLoading && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'rgba(255, 255, 255, 0.7)',
            zIndex: 9999,
          }}
        >
          <Loading size="large" />
        </div>
      )}
      <AppRouter />
    </div>
  );
}

export default App;
