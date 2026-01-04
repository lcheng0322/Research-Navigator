import { Card, Button } from 'tdesign-react';
import { 
  FolderIcon,
  SearchIcon,
  BookIcon,
  AnalyticsIcon,
  TableIcon,
  SettingIcon,
  TaskIcon
} from 'tdesign-icons-react';
import { useNavigate } from 'react-router-dom';

const DashboardPage = () => {
  const navigate = useNavigate();

  const quickLinks = [
    { label: '文档管理', desc: '上传与管理你的文献与数据文件', icon: <FolderIcon size="24px" />, path: '/documents' },
    { label: '智能查询', desc: '在知识库中提出问题并获取答案', icon: <SearchIcon size="24px" />, path: '/query' },
    { label: '文献综述', desc: '生成主题的结构化综述与提纲', icon: <BookIcon size="24px" />, path: '/literature-review' },
    { label: '缺口分析', desc: '发现主题聚类与潜在研究缺口', icon: <AnalyticsIcon size="24px" />, path: '/gap-analysis' },
    { label: '数据分析', desc: '上传表格数据进行分析与可视化', icon: <TableIcon size="24px" />, path: '/tabular-analysis' },
    { label: '实验设计', desc: '基于知识库生成与完善研究实验方案', icon: <SettingIcon size="24px" />, path: '/experiment-design' },
    { label: '任务中心', desc: '查看与管理后台异步任务进度', icon: <TaskIcon size="24px" />, path: '/tasks' },
  ];

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">仪表板</h1>
        <p className="page-subtitle">请选择要进入的功能。以下为侧导航栏的快速跳转。</p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '24px' }}>
        {quickLinks.map((item) => (
          <Card key={item.path} className="card">
            <div className="card-body" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <div className="w-12 h-12 rounded-lg flex items-center justify-center" style={{ backgroundColor: 'var(--color-primary-alpha)' }}>
                <span style={{ color: 'var(--color-primary)' }}>{item.icon}</span>
              </div>
              <div style={{ flex: 1 }}>
                <div className="text-sm font-medium text-primary">{item.label}</div>
                <div className="text-xs text-secondary" style={{ marginTop: 6 }}>{item.desc}</div>
              </div>
              <Button theme="primary" className="btn btn-primary" onClick={() => navigate(item.path)}>
                前往
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};

export default DashboardPage;
