import { Form, Input, Button, MessagePlugin, Card, Alert } from 'tdesign-react';
import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import apiClient from '../services/api';

const { FormItem, useForm } = Form;

const RegisterPage = () => {
  const [form] = useForm();
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: any) => {
    if (e.validateResult.length > 0) {
      return;
    }

    const values = form.getFieldsValue(true);
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      await apiClient.post('/users/', {
        email: values.email,
        password: values.password,
      });
      MessagePlugin.success('Registration successful! You can now log in.');
      navigate('/login');
    } catch (error: any) {
      const detail = error.response?.data?.detail ?? 'Registration failed. Please try again.';
      setErrorMessage(detail);
      MessagePlugin.error(detail);
      console.error('Registration error:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: 'var(--bg-page)' }}>
      <Card className="card" style={{ width: 420 }}>
        <div className="card-body">
          <div className="page-header" style={{padding: 0, border: 'none', textAlign: 'center'}}>
            <h1 className="page-title">Create an Account</h1>
          </div>
          {errorMessage && <Alert theme="error" message={errorMessage} style={{marginBottom: 'var(--spacing-4)'}}/>}
          <Form form={form} layout="vertical" onSubmit={handleSubmit}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-6)' }}>
                <div className="input-group">
                    <label className="input-label required">Email</label>
                    <FormItem
                      name="email"
                      rules={[{ required: true, message: 'Email is required' }, { email: true, message: 'Please enter a valid email' }]}
                      style={{margin: 0}}
                    >
                      <Input className="input" placeholder="you@example.com" />
                    </FormItem>
                </div>
                <div className="input-group">
                    <label className="input-label required">Password</label>
                    <FormItem
                      name="password"
                      rules={[{ required: true, message: 'Password is required' }, { min: 6, message: 'Minimum 6 characters' }]}
                      style={{margin: 0}}
                    >
                      <Input type="password" className="input" placeholder="Enter your password" />
                    </FormItem>
                </div>
                <div className="input-group">
                    <label className="input-label required">Confirm Password</label>
                    <FormItem name="confirmPassword" rules={[
                      { required: true, message: 'Please confirm your password' },
                      {
                        validator: (val: string) => {
                          if (val !== form.getFieldValue('password')) {
                            return { result: false, message: 'Passwords do not match' };
                          }
                          return true;
                        },
                      },
                    ]} style={{margin: 0}}>
                      <Input type="password" className="input" placeholder="Confirm your password" />
                    </FormItem>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <Button type="submit" theme="primary" block loading={isSubmitting} className="btn btn-primary">
                    {isSubmitting ? 'Registering...' : 'Register'}
                  </Button>
                </div>
            </div>
          </Form>
          <p style={{ textAlign: 'center', marginTop: 'var(--spacing-4)' }}>
            Already have an account? <Link to="/login">Log in</Link>
          </p>
        </div>
      </Card>
    </div>
  );
};

export default RegisterPage;
