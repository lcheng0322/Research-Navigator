import React from 'react';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  text?: string;
}

const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ 
  size = 'md', 
  className = '', 
  text 
}) => {
  const sizeClasses = {
    sm: 'loading-spinner',
    md: 'loading-spinner',
    lg: 'loading-spinner loading-spinner-lg'
  };

  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <div className={sizeClasses[size]} />
      {text && (
        <span className="text-sm text-secondary animate-pulse">
          {text}
        </span>
      )}
    </div>
  );
};

export default LoadingSpinner;