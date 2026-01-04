import { Navigate, Outlet } from 'react-router-dom';
import useAuthStore from '../store/authStore';
import { useEffect, useState } from 'react';

const ProtectedRoute = () => {
  const token = useAuthStore((state) => state.token);
  
  // This state tracks whether Zustand has finished rehydrating from localStorage
  const [hasHydrated, setHasHydrated] = useState(useAuthStore.persist.hasHydrated());

  useEffect(() => {
    // Listen for the end of the rehydration process
    const unsubscribe = useAuthStore.persist.onFinishHydration(() => {
      setHasHydrated(true);
    });

    return unsubscribe; // Cleanup the listener on unmount
  }, []);

  // If hydration is not complete, don't render anything yet (or a loading spinner)
  if (!hasHydrated) {
    return null;
  }

  // Once hydrated, check for the token
  if (token) {
    return <Outlet />;
  }

  // If there is no token, redirect to the /login page
  return <Navigate to="/login" replace />;
};

export default ProtectedRoute;
