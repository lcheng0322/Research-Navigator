import { Layout, Menu, Dropdown, Avatar, Space, Typography, Badge } from 'tdesign-react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import useAuthStore from '../store/authStore';
import { 
  UserIcon, 
  LogoutIcon, 
  DashboardIcon,
  FolderIcon,
  SearchIcon,
  BookIcon,
  AnalyticsIcon,
  TableIcon,
  SettingIcon,
  TaskIcon
} from 'tdesign-icons-react';

const { Text } = Typography;

const MainLayout = () => {
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);
  const fetchCurrentUser = useAuthStore((state) => state.fetchCurrentUser);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!user) {
      fetchCurrentUser();
    }
  }, [user, fetchCurrentUser]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const dropdownOptions = [
    {
      content: '退出登录',
      value: 'logout',
      onClick: handleLogout,
      prefixIcon: <LogoutIcon />,
    },
  ];

  // 菜单项配置
  const menuItems = [
    { value: 'dashboard', label: '仪表板', icon: <DashboardIcon /> },
    { value: 'documents', label: '文档管理', icon: <FolderIcon /> },
    { value: 'query', label: '智能查询', icon: <SearchIcon /> },
    { value: 'literature-review', label: '文献综述', icon: <BookIcon /> },
    { value: 'gap-analysis', label: '缺口分析', icon: <AnalyticsIcon /> },
    { value: 'tabular-analysis', label: '数据分析', icon: <TableIcon /> },
    { value: 'experiment-design', label: '实验设计', icon: <SettingIcon /> },
    { value: 'tasks', label: '任务中心', icon: <TaskIcon /> },

  ];

  return (
    <div className="app-container">
      <Layout style={{ minHeight: '100vh', backgroundColor: 'var(--bg-secondary)' }}>
        {/* 侧边栏 */}
        <Layout.Aside style={{ 
          backgroundColor: 'var(--bg-primary)', 
          borderRight: '1px solid var(--border-primary)',
          boxShadow: 'var(--shadow-sm)'
        }}>
          {/* Logo 区域 */}
          <div style={{ 
            height: '64px', 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'center',
            borderBottom: '1px solid var(--border-primary)',
            backgroundColor: 'var(--bg-primary)'
          }}>
            <div style={{
              fontSize: 'var(--font-size-lg)',
              fontWeight: 'var(--font-weight-bold)',
              color: 'var(--color-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--spacing-2)'
            }}>
              <SearchIcon size="24px" />
              Research Navigator
            </div>
          </div>
          
          {/* 导航菜单 */}
          <div style={{ padding: 'var(--spacing-4) var(--spacing-2)' }}>
            <Menu
              theme="light"
              value={location.pathname.substring(1)}
              onChange={(value) => navigate(`/${value}`)}
              style={{ 
                backgroundColor: 'transparent',
                border: 'none'
              }}
            >
              {menuItems.map(item => (
                <Menu.MenuItem 
                  key={item.value} 
                  value={item.value}
                  style={{
                    margin: 'var(--spacing-1) 0',
                    borderRadius: 'var(--radius-md)',
                    transition: 'all var(--transition-fast)'
                  }}
                >
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: 'var(--spacing-3)',
                    padding: 'var(--spacing-1) var(--spacing-2)'
                  }}>
                    <span style={{ color: 'var(--color-primary)' }}>
                      {item.icon}
                    </span>
                    <span style={{ 
                      fontSize: 'var(--font-size-sm)',
                      fontWeight: 'var(--font-weight-medium)'
                    }}>
                      {item.label}
                    </span>
                  </div>
                </Menu.MenuItem>
              ))}
            </Menu>
          </div>
        </Layout.Aside>

        <Layout>
          {/* 顶部导航栏 */}
          <Layout.Header style={{ 
            backgroundColor: 'var(--bg-primary)', 
            padding: '0 var(--spacing-6)', 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center',
            borderBottom: '1px solid var(--border-primary)',
            boxShadow: 'var(--shadow-sm)',
            height: '64px'
          }}>
            {/* 页面标题区域 */}
            <div>
              <Text style={{ 
                fontSize: 'var(--font-size-lg)',
                fontWeight: 'var(--font-weight-semibold)',
                color: 'var(--text-primary)'
              }}>
                {menuItems.find(item => item.value === location.pathname.substring(1))?.label || '研究导航'}
              </Text>
            </div>

            {/* 用户信息区域 */}
            <Space align="center" size="large">
              {/* 在线状态指示器 */}
              <div className="status-indicator status-online">
                <div className="status-dot"></div>
                <span>在线</span>
              </div>

              {/* 用户信息 */}
              <div style={{ textAlign: 'right' }}>
                <Text style={{ 
                  fontSize: 'var(--font-size-sm)',
                  fontWeight: 'var(--font-weight-medium)',
                  color: 'var(--text-primary)'
                }}>
                  {user?.email ?? '加载用户信息...'}
                </Text>
                {user && (
                  <div>
                    <Badge 
                      count={user.is_active ? '活跃' : '未激活'} 
                      color={user.is_active ? 'var(--color-success)' : 'var(--color-error)'}
                      style={{ 
                        fontSize: 'var(--font-size-xs)',
                        marginTop: 'var(--spacing-1)'
                      }}
                    />
                  </div>
                )}
              </div>

              {/* 用户头像和下拉菜单 */}
              <Dropdown options={dropdownOptions}>
                <Avatar 
                  icon={<UserIcon />} 
                  style={{
                    backgroundColor: 'var(--color-primary)',
                    cursor: 'pointer',
                    transition: 'all var(--transition-fast)'
                  }}
                />
              </Dropdown>
            </Space>
          </Layout.Header>

          {/* 主内容区域 */}
          <Layout.Content className="main-content">
            <div style={{ 
              padding: 'var(--spacing-6)', 
              backgroundColor: 'var(--bg-primary)', 
              minHeight: '400px',
              borderRadius: 'var(--radius-lg)',
              boxShadow: 'var(--shadow-sm)',
              border: '1px solid var(--border-primary)'
            }}>
              <Outlet />
            </div>
          </Layout.Content>

          {/* 底部 */}
          <Layout.Footer style={{ 
            textAlign: 'center',
            padding: 'var(--spacing-4)',
            backgroundColor: 'var(--bg-primary)',
            borderTop: '1px solid var(--border-primary)',
            color: 'var(--text-secondary)',
            fontSize: 'var(--font-size-sm)'
          }}>
            Research Navigator ©{new Date().getFullYear()} - 科研级RAG系统
          </Layout.Footer>
        </Layout>
      </Layout>
    </div>
  );
};

export default MainLayout;
