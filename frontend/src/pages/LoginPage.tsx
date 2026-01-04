import { useState } from 'react';
import { Form, Input, Button, MessagePlugin, Card } from 'tdesign-react';
import { useNavigate, Link } from 'react-router-dom';
import apiClient from '../services/api';
import useAuthStore from '../store/authStore';

const { FormItem, useForm } = Form;

const LoginPage = () => {
  const navigate = useNavigate();
  const { setToken, fetchCurrentUser } = useAuthStore();
  const [form] = useForm();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (e: any) => {
    if (e.validateResult.length > 0) {
      return; // Validation failed
    }
    const values = form.getFieldsValue(true);
    setIsSubmitting(true);
    try {
      const response = await apiClient.post('/token', new URLSearchParams(values));
      const { access_token } = response.data;
      setToken(access_token);
      await fetchCurrentUser();
      MessagePlugin.success('Login successful!');
      navigate('/dashboard');
    } catch (error) {
      MessagePlugin.error('Login failed. Please check your credentials.');
      console.error('Login error:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: 'var(--bg-page)' }}>
      <Card className="card" style={{ width: 400 }}>
        <div className="card-body">
            <div className="page-header" style={{padding: 0, border: 'none', textAlign: 'center'}}>
                <h1 className="page-title">Login</h1>
            </div>
            <Form form={form} onSubmit={onSubmit} layout="vertical">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-6)' }}>
                    <div className="input-group">
                        <label className="input-label required">Email</label>
                        <FormItem name="username" rules={[{ required: true, message: 'Email is required' }]} style={{margin: 0}}>
                            <Input className="input" placeholder="you@example.com" />
                        </FormItem>
                    </div>
                    <div className="input-group">
                        <label className="input-label required">Password</label>
                        <FormItem name="password" rules={[{ required: true, message: 'Password is required' }]} style={{margin: 0}}>
                            <Input type="password" className="input" placeholder="Password" />
                        </FormItem>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button type="submit" theme="primary" block loading={isSubmitting} className="btn btn-primary">
                            {isSubmitting ? 'Logging in...' : 'Login'}
                        </Button>
                    </div>
                </div>
            </Form>
            <p style={{ textAlign: 'center', marginTop: 'var(--spacing-4)' }}>
                Don't have an account? <Link to="/register">Register here</Link>
            </p>
        </div>
      </Card>
    </div>
  );
};

export default LoginPage;
