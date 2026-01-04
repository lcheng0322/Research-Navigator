import React from 'react';

interface SkeletonLoaderProps {
  type?: 'text' | 'avatar' | 'button' | 'card' | 'table';
  lines?: number;
  className?: string;
}

const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({ 
  type = 'text', 
  lines = 3, 
  className = '' 
}) => {
  const renderSkeleton = () => {
    switch (type) {
      case 'avatar':
        return <div className="skeleton skeleton-avatar" />;
      
      case 'button':
        return <div className="skeleton skeleton-button" />;
      
      case 'card':
        return (
          <div className={`card ${className}`}>
            <div className="card-header">
              <div className="flex items-center gap-3">
                <div className="skeleton skeleton-avatar" />
                <div className="flex-1">
                  <div className="skeleton skeleton-text" style={{ width: '60%' }} />
                  <div className="skeleton skeleton-text" style={{ width: '40%' }} />
                </div>
              </div>
            </div>
            <div className="card-body">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="skeleton skeleton-text" />
              ))}
            </div>
          </div>
        );
      
      case 'table':
        return (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  {Array.from({ length: 4 }).map((_, i) => (
                    <th key={i}>
                      <div className="skeleton skeleton-text" />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 5 }).map((_, rowIndex) => (
                  <tr key={rowIndex}>
                    {Array.from({ length: 4 }).map((_, colIndex) => (
                      <td key={colIndex}>
                        <div className="skeleton skeleton-text" />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      
      case 'text':
      default:
        return (
          <div className={className}>
            {Array.from({ length: lines }).map((_, i) => (
              <div key={i} className="skeleton skeleton-text" />
            ))}
          </div>
        );
    }
  };

  return renderSkeleton();
};

export default SkeletonLoader;