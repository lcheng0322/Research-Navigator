import { useState } from 'react';
import { Input, Button, Card, Alert, Loading, MessagePlugin, Typography, List, Steps, Textarea, Form } from 'tdesign-react';
import { saveAs } from 'file-saver';
import useTaskStream from '../hooks/useTaskStream';
import useTaskStore from '../store/taskStore';
import apiClient from '../services/api';

const { Title, Paragraph } = Typography;
const Step = Steps.StepItem;

const LiteratureReviewPage = () => {
  const [currentStep, setCurrentStep] = useState(0);
  const [topic, setTopic] = useState('');
  const [outline, setOutline] = useState<any>(null);
  const [contextId, setContextId] = useState<string | null>(null);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const taskRecord = useTaskStore((state) =>
    currentTaskId ? state.tasks.find((task) => task.taskId === currentTaskId) : undefined
  );

  useTaskStream({
    taskId: currentTaskId,
    taskType: 'literature-review',
    title: topic ? `Literature Review: ${topic}` : 'Literature Review',
    immediate: true,
    onTaskSuccess: () => MessagePlugin.success('Literature review generated successfully!'),
    onTaskFailure: () => MessagePlugin.error('Task failed to generate literature review.'),
  });

  const handleGenerateOutline = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setError(null);
    setOutline(null);
    setContextId(null);
    setCurrentTaskId(null);

    const params = new URLSearchParams();
    params.append('topic', topic);

    try {
      const response = await apiClient.post('/generate/literature-review/outline', params, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      setOutline(response.data.outline);
      setContextId(response.data.context_id);
      setCurrentStep(1);
      MessagePlugin.success('Outline generated successfully!');
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || 'Failed to generate outline.';
      setError(errorMessage);
      MessagePlugin.error(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateReview = async () => {
    if (!outline || !contextId) return;
    setLoading(true);
    setError(null);

    try {
      const response = await apiClient.post('/generate/literature-review/from-outline', {
        outline: outline,
        context_id: contextId,
      });
      const { task_id } = response.data;
      setCurrentTaskId(task_id);
      setCurrentStep(2);
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || 'Failed to start review generation.';
      setError(errorMessage);
      MessagePlugin.error(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadDocx = async () => {
    if (!currentTaskId) return;
    try {
      const response = await apiClient.get(`/generate/literature-review/download/${currentTaskId}`, {
        responseType: 'blob',
      });
      saveAs(response.data, `literature_review_${topic.replace(/\s+/g, '_')}.docx`);
    } catch (error) {
      MessagePlugin.error('Failed to download DOCX file.');
      console.error(error);
    }
  };

  const renderStepContent = () => {
    switch (currentStep) {
      case 0:
        return (
          <Form onSubmit={handleGenerateOutline}>
            <div className="input-group">
              <label htmlFor="topic-input" className="input-label required">Topic</label>
              <Input
                className="input"
                value={topic}
                onChange={(value) => setTopic(String(value))}
                placeholder="e.g., Thermochemical treatment of sewage sludge ash"
              />
              <p className="input-help">The model will generate a review based on this topic.</p>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--spacing-4)' }}>
              <Button type="submit" theme="primary" className="btn btn-primary" loading={loading} disabled={!topic.trim()}>
                Generate Outline
              </Button>
            </div>
          </Form>
        );
      case 1:
        return (
          <div>
            <Title level="h5">Review and Edit Outline</Title>
            <Textarea
              value={JSON.stringify(outline, null, 2)}
              onChange={(val) => setOutline(JSON.parse(String(val)))}
              autosize={{ minRows: 15 }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'var(--spacing-4)' }}>
              <Button theme="default" onClick={() => setCurrentStep(0)}>Back</Button>
              <Button theme="primary" onClick={handleGenerateReview} loading={loading}>
                Generate Full Review
              </Button>
            </div>
          </div>
        );
      case 2:
        return (
          <div>
            {taskRecord && (
              <Card
                actions={
                  <Button theme="primary" variant="outline" onClick={handleDownloadDocx} disabled={taskRecord.status !== 'SUCCESS'}>
                    Download as DOCX
                  </Button>
                }
              >
                <p><strong>Task Status:</strong> {taskRecord.status}</p>
                {(taskRecord.status === 'PENDING' || taskRecord.status === 'STARTED') && <Loading text="Generating full review..." />}
                {taskRecord.status === 'SUCCESS' && taskRecord.result && (
                  <div>
                    <Title level="h5">{taskRecord.result.title}</Title>
                    {Object.entries(taskRecord.result.content).map(([section, text]) => (
                      <div key={section}>
                        <Title level="h6">{section}</Title>
                        <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{String(text)}</Paragraph>
                      </div>
                    ))}
                    <Title level="h6">References</Title>
                    <List>
                      {Object.entries(taskRecord.result.references)
                        .sort(([aKey], [bKey]) => aKey.localeCompare(bKey, undefined, { numeric: true, sensitivity: 'base' }))
                        .map(([key, value]) => (
                          <List.ListItem key={key}>{`${key}: ${value}`}</List.ListItem>
                        ))}
                    </List>
                  </div>
                )}
                {taskRecord.status === 'FAILURE' && <Alert theme="error" title="Task Failed" message={String(taskRecord.result)} />}
              </Card>
            )}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">Literature Review Generation</h1>
        <p className="page-subtitle">Follow the steps to generate a literature review from your knowledge base.</p>
      </div>

      <Card className="card">
        <div className="card-body">
          <Steps current={currentStep}>
            <Step title="Enter Topic" content="Provide the main research topic." />
            <Step title="Review Outline" content="Review and edit the generated outline." />
            <Step title="Generate & Download" content="Generate the full review and download the document." />
          </Steps>

          <div style={{ marginTop: '24px' }}>
            {error && <Alert theme="error" message={error} style={{ marginBottom: 20 }} />}
            {renderStepContent()}
          </div>
        </div>
      </Card>
    </div>
  );
};

export default LiteratureReviewPage;
