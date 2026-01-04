import React from 'react';

interface StatusBadgeProps {
  status: 'success' | 'warning' | 'error' | 'info' | 'processing';
  text?: string;
  size?: 'sm' | 'md';
  className?: string;
}

const StatusBadge: React.FC<StatusBadgeProps> = ({ 
  status, 
  text, 
  size = 'md',
  className = '' 
}) => {
  const getStatusConfig = () => {
    switch (status) {
      case 'success':
        return {
          className: 'badge-success',
          defaultText: '成功'
        };
      case 'warning':
        return {
          className: 'badge-warning',
          defaultText: '警告'
        };
      case 'error':
        return {
          className: 'badge-error',
          defaultText: '错误'
        };
      case 'processing':
        return {
          className: 'badge-primary',
          defaultText: '处理中'
        };
      case 'info':
      default:
        return {
          className: 'badge-secondary',
          defaultText: '信息'
        };
    }
  };

  const config = getStatusConfig();
  const displayText = text || config.defaultText;
  const sizeClass = size === 'sm' ? 'text-xs' : '';

  return (
    <span className={`badge ${config.className} ${sizeClass} ${className}`}>
      {status === 'processing' && (
        <span className="loading-spinner" style={{ 
          width: '12px', 
          height: '12px', 
          marginRight: 'var(--spacing-1)',
          borderWidth: '1px'
        }} />
      )}
      {displayText}
    </span>
  );
};

export default StatusBadge;