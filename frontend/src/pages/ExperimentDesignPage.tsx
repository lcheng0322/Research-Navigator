import { useState } from 'react';
import { Form, Button, Card, Loading, Alert, Textarea, MessagePlugin, Typography, List, Table, Tag, Divider, Steps } from 'tdesign-react';
import { saveAs } from 'file-saver';
import type { TableProps } from 'tdesign-react';
import apiClient from '../services/api';

const { FormItem } = Form;
const { Title, Paragraph } = Typography;
const Step = Steps.StepItem;

// Interfaces matching backend schemas
interface Hypothesis {
  hypothesis_text: string;
  context_summary: string;
}

interface ExperimentStep {
  step_number: number;
  description: string;
  materials_needed?: string[] | null;
}

interface ExperimentDesign {
  title: string;
  hypothesis: string;
  methodology: string;
  materials: string[];
  control_group: string;
  experimental_group: string;
  steps: ExperimentStep[];
  data_analysis_plan: string;
  potential_risks?: string | null;
}

const ExperimentDesignPage = () => {
  const [currentStep, setCurrentStep] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // State for the entire session
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [researchTopic, setResearchTopic] = useState('');
  const [initialHypothesis, setInitialHypothesis] = useState<Hypothesis | null>(null);
  const [fullDesign, setFullDesign] = useState<ExperimentDesign | null>(null);
  const [refinedDesign, setRefinedDesign] = useState<ExperimentDesign | null>(null);

  const handleDownloadDocx = async () => {
    if (!sessionId) return;
    try {
      const response = await apiClient.get(`/experiments/${sessionId}/download`, {
        responseType: 'blob',
      });
      const safeTopic = (researchTopic || 'experiment_design').replace(/\s+/g, '_');
      saveAs(response.data, `${safeTopic}.docx`);
      MessagePlugin.success('DOCX 下载成功');
    } catch (error) {
      MessagePlugin.error('DOCX 下载失败');
      console.error(error);
    }
  };

  const stepColumns: TableProps['columns'] = [
    { colKey: 'step_number', title: 'Step' },
    { colKey: 'description', title: 'Description' },
    { colKey: 'materials_needed', title: 'Materials', cell: ({ row }) => 
        (row.materials_needed && row.materials_needed.length > 0) ? 
        row.materials_needed.map((m: string) => <Tag key={m}>{m}</Tag>) : 'N/A' },
  ];

  const handleStartSession = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.post('/experiments', { research_topic: researchTopic });
      const { session_id, hypothesis } = response.data;
      setSessionId(session_id);
      setInitialHypothesis(hypothesis);
      setCurrentStep(1);
      MessagePlugin.success('Session started and initial hypothesis generated.');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start session.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGenerateDesign = async () => {
    if (!sessionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.post(`/experiments/${sessionId}/design`);
      setFullDesign(response.data);
      setCurrentStep(2);
      MessagePlugin.success('Full experimental design generated.');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate design.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefineDesign = async () => {
    if (!sessionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.post(`/experiments/${sessionId}/refine`);
      setRefinedDesign(response.data);
      MessagePlugin.success('Design has been refined.');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to refine design.');
    } finally {
      setIsLoading(false);
    }
  };

  const resetState = () => {
    setCurrentStep(0);
    setSessionId(null);
    setResearchTopic('');
    setInitialHypothesis(null);
    setFullDesign(null);
    setRefinedDesign(null);
    setError(null);
  };

  const renderFullDesign = (design: ExperimentDesign) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <Title level="h5">{design.title}</Title>
        <Paragraph><strong>Hypothesis:</strong> {design.hypothesis}</Paragraph>
        <Paragraph><strong>Methodology:</strong> {design.methodology}</Paragraph>
        <Divider />
        <Card title="Materials & Groups">
            <List>
                <List.ListItem><strong>Control Group:</strong> {design.control_group}</List.ListItem>
                <List.ListItem><strong>Experimental Group:</strong> {design.experimental_group}</List.ListItem>
            </List>
            <Paragraph style={{ marginTop: 16 }}><strong>All Materials Needed:</strong></Paragraph>
            <div>{design.materials.map(item => <Tag key={item} style={{margin: '2px'}}>{item}</Tag>)}</div>
        </Card>
        <Divider />
        <Card title="Detailed Steps">
            <Table rowKey="step_number" data={design.steps} columns={stepColumns} bordered stripe />
        </Card>
        <Divider />
        <Paragraph><strong>Data Analysis Plan:</strong> {design.data_analysis_plan}</Paragraph>
        {design.potential_risks && <Paragraph><strong>Potential Risks:</strong> {design.potential_risks}</Paragraph>}
    </div>
  );

  const renderStepContent = () => {
    switch (currentStep) {
      case 0:
        return (
          <Form onSubmit={handleStartSession} layout="vertical">
            <FormItem label="Research Topic" name="research_topic">
              <Textarea placeholder="e.g., The effect of caffeine on short-term memory recall in college students" value={researchTopic} onChange={setResearchTopic} autosize={{ minRows: 3 }} />
            </FormItem>
            <Button theme="primary" type="submit" loading={isLoading} disabled={!researchTopic.trim()}>Start Design Session</Button>
          </Form>
        );
      case 1:
        return (
          <Card title="Step 2: Review Initial Hypothesis">
            {initialHypothesis && (
              <div>
                <Paragraph><strong>Generated Hypothesis:</strong> {initialHypothesis.hypothesis_text}</Paragraph>
                <Paragraph><strong>Justification from Knowledge Base:</strong> {initialHypothesis.context_summary}</Paragraph>
              </div>
            )}
            <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'space-between' }}>
              <Button theme="default" onClick={resetState}>Start Over</Button>
              <Button theme="primary" onClick={handleGenerateDesign} loading={isLoading}>Generate Full Design</Button>
            </div>
          </Card>
        );
      case 2:
        return (
          <Card title="Step 3: Review and Refine Design">
            {fullDesign && renderFullDesign(fullDesign)}
            <Divider />
            {refinedDesign && (
                <div style={{marginTop: '16px'}}>
                    <Title level="h5">Refined Design</Title>
                    {renderFullDesign(refinedDesign)}
                </div>
            )}
            <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'space-between' }}>
              <Button theme="default" onClick={resetState}>Start Over</Button>
              <div style={{ display: 'flex', gap: 12 }}>
                <Button theme="primary" variant="outline" onClick={handleRefineDesign} loading={isLoading} disabled={!!refinedDesign}>Review & Refine with AI Critic</Button>
                <Button theme="primary" onClick={handleDownloadDocx} disabled={!sessionId || (!fullDesign && !refinedDesign)}>Download as DOCX</Button>
              </div>
            </div>
          </Card>
        );
      default:
        return null;
    }
  };

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">Interactive Experiment Designer</h1>
        <p className="page-subtitle">Design a scientific experiment step-by-step with AI assistance.</p>
      </div>

      <Card className="card">
        <div className="card-body">
          <Steps current={currentStep} readonly>
            <Step title="Define Topic" content="Start with your research question." />
            <Step title="Review Hypothesis" content="Review the AI-generated hypothesis." />
            <Step title="Generate & Refine" content="Generate and optionally refine the full design." />
          </Steps>
          <div style={{ marginTop: '24px' }}>
            {error && <Alert theme="error" message={error} style={{ marginBottom: 20 }} />}
            {isLoading && currentStep === 0 && <Loading text="Starting session..." />}
            {renderStepContent()}
          </div>
        </div>
      </Card>
    </div>
  );
};

export default ExperimentDesignPage;
