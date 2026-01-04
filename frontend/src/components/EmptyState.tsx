import React from 'react';
import { Button } from 'tdesign-react';
import { FolderOpenIcon, SearchIcon, FileIcon } from 'tdesign-icons-react';

interface EmptyStateProps {
  type?: 'no-data' | 'no-results' | 'no-files' | 'custom';
  title?: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
  icon?: React.ReactNode;
  className?: string;
}

const EmptyState: React.FC<EmptyStateProps> = ({
  type = 'no-data',
  title,
  description,
  actionText,
  onAction,
  icon,
  className = ''
}) => {
  const getDefaultContent = () => {
    switch (type) {
      case 'no-results':
        return {
          icon: <SearchIcon size="64px" />,
          title: '未找到相关结果',
          description: '尝试调整搜索条件或使用不同的关键词'
        };
      
      case 'no-files':
        return {
          icon: <FileIcon size="64px" />,
          title: '暂无文件',
          description: '上传您的第一个文档开始使用系统'
        };
      
      case 'no-data':
      default:
        return {
          icon: <FolderOpenIcon size="64px" />,
          title: '暂无数据',
          description: '这里还没有任何内容'
        };
    }
  };

  const defaultContent = getDefaultContent();
  const displayIcon = icon || defaultContent.icon;
  const displayTitle = title || defaultContent.title;
  const displayDescription = description || defaultContent.description;

  return (
    <div className={`empty-state ${className}`}>
      <div className="empty-state-icon">
        {displayIcon}
      </div>
      
      <h3 className="empty-state-title">
        {displayTitle}
      </h3>
      
      <p className="empty-state-description">
        {displayDescription}
      </p>
      
      {actionText && onAction && (
        <Button 
          theme="primary" 
          onClick={onAction}
          className="btn btn-primary"
        >
          {actionText}
        </Button>
      )}
    </div>
  );
};

export default EmptyState;