import { useState, useCallback, useEffect } from 'react';
import { Button, Card, Alert, Loading, MessagePlugin, Tag, Statistic, List, Typography, Collapse, Table } from 'tdesign-react';
import { saveAs } from 'file-saver';
import Plot from 'react-plotly.js';
import useTaskStream from '../hooks/useTaskStream';
import useTaskStore, { type TaskRecord } from '../store/taskStore';
import apiClient from '../services/api';

const { Title, Paragraph, Text } = Typography;
const { Panel } = Collapse;

interface Topic {
  Topic: number;
  Count: number;
  Name: string;
  Representation: string[];
}

interface OutlierDocument {
  text: string;
  metadata: {
    source: string;
    page_number?: number;
  };
}

interface AnalysisSummary {
  total_documents_analyzed: number;
  total_topics_found: number;
  outlier_documents_count: number;
  topics: Topic[];
  outlier_documents: OutlierDocument[];
  trends?: Array<{ Timestamp: string; Topic: number; Frequency: number }>;
  research_gap_suggestion?: string;
}

// Helper function to format topic names
const formatTopicName = (name: string): string => {
  return name
    .split('_')
    .slice(1)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' & ');
};

const SESSION_STORAGE_KEY = 'gapAnalysisPage_currentTaskId';

const GapAnalysisPage = () => {
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_STORAGE_KEY)
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysisSummary, setAnalysisSummary] = useState<AnalysisSummary | null>(null);

  const taskRecord = useTaskStore((state) =>
    currentTaskId ? state.tasks.find((task) => task.taskId === currentTaskId) : undefined
  ) as TaskRecord | undefined;

  useEffect(() => {
    if (currentTaskId) {
      sessionStorage.setItem(SESSION_STORAGE_KEY, currentTaskId);
    } else {
      sessionStorage.removeItem(SESSION_STORAGE_KEY);
    }
  }, [currentTaskId]);

  const onTaskSuccess = useCallback((result: any) => {
    MessagePlugin.success('Gap analysis completed successfully!');
    setAnalysisSummary(result as AnalysisSummary);
  }, []);

  const onTaskFailure = useCallback(() => {
    MessagePlugin.error('Task failed to perform gap analysis.');
  }, []);

  useTaskStream({
    taskId: currentTaskId,
    taskType: 'gap-analysis',
    title: 'Gap Analysis',
    immediate: true,
    onTaskSuccess,
    onTaskFailure,
  });

  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    setAnalysisSummary(null);
    setCurrentTaskId(null);

    try {
      const response = await apiClient.post('/analyze/research-gaps/', {});
      const { task_id } = response.data;
      setCurrentTaskId(task_id);
    } catch (err) {
      setError('Failed to start the analysis task. Please try again.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadDocx = async () => {
    if (!currentTaskId) return;
    try {
      const response = await apiClient.get(`/analyze/research-gaps/download/${currentTaskId}`,
        { responseType: 'blob' }
      );
      saveAs(response.data, `gap_analysis_${currentTaskId}.docx`);
      MessagePlugin.success('DOCX 下载成功');
    } catch (err) {
      MessagePlugin.error('DOCX 下载失败');
      console.error(err);
    }
  };

  const isTaskRunning = !!taskRecord && taskRecord.status !== 'SUCCESS' && taskRecord.status !== 'FAILURE';

  const mainTopics = analysisSummary?.topics.filter(t => t.Topic !== -1) || [];
  // const outlierTopic = analysisSummary?.topics.find(t => t.Topic === -1);

  const renderTrendChart = (trends: AnalysisSummary['trends'], topics: Topic[]) => {
    if (!trends || trends.length === 0) return <p>Trend data is not available.</p>;

    const topicNames = topics.reduce<Record<number, string>>((acc, topic) => {
      acc[topic.Topic] = formatTopicName(topic.Name);
      return acc;
    }, {});

    const data = trends.reduce<Record<number, any>>((acc, trend) => {
      const topicId = trend.Topic;
      if (topicId === -1) return acc; // Skip noise topic

      if (!acc[topicId]) {
        acc[topicId] = {
          x: [],
          y: [],
          type: 'scatter',
          mode: 'lines+markers',
          name: topicNames[topicId] || `Topic ${topicId}`,
        };
      }
      acc[topicId].x.push(trend.Timestamp);
      acc[topicId].y.push(trend.Frequency);
      return acc;
    }, {});

    return (
      <Plot
        data={Object.values(data)}
        layout={{
          title: { text: 'Topic Popularity Over Time' },
          xaxis: { title: { text: 'Year' } },
          yaxis: { title: { text: 'Topic Frequency' } },
        }}
      />
    );
  };

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">Research Gap Analysis</h1>
        <p className="page-subtitle">Identify thematic clusters and potential research gaps in your knowledge base.</p>
      </div>

      <Card className="card">
        <div className="card-body">
          <p className="input-help" style={{marginBottom: 'var(--spacing-4)'}}>This tool performs topic modeling on the entire knowledge base to identify thematic clusters and potential research gaps. It helps visualize the main research areas and discover less-explored ones.</p>
          <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
            <Button
              theme="primary"
              className="btn btn-primary"
              loading={loading || isTaskRunning}
              disabled={isTaskRunning}
              onClick={handleAnalyze}
            >
              {isTaskRunning ? 'Analyzing...' : 'Start Gap Analysis'}
            </Button>
          </div>
        </div>
      </Card>

      {error && <Alert theme="error" message={error} style={{ marginTop: 20 }} />}

      {isTaskRunning && !analysisSummary && (
         <Card className="card" style={{ marginTop: 20 }}>
            <div className="card-body">
                <Loading text="Analysis in progress... This may take several minutes." />
                <p><strong>Status:</strong> {taskRecord?.status}</p>
            </div>
         </Card>
      )}

      {analysisSummary && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-6)', marginTop: 'var(--spacing-6)' }}>
            {/* --- Summary Statistics --- */}
            <Card>
                <div className="card-body">
                    <div style={{ display: 'flex', justifyContent: 'space-around'}}>
                        <Statistic title="Total Documents Analyzed" value={analysisSummary.total_documents_analyzed} />
                        <Statistic title="Core Topics Found" value={analysisSummary.total_topics_found} />
                        <Statistic title="Potential Gaps (Outliers)" value={analysisSummary.outlier_documents_count} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--spacing-4)'}}>
                      <Button theme="primary" onClick={handleDownloadDocx} disabled={!currentTaskId}>Download as DOCX</Button>
                    </div>
                </div>
            </Card>

            {analysisSummary.research_gap_suggestion && (
              <Card>
                <div className="card-body">
                  <Alert theme="info" title="Research Direction Suggestion" message={analysisSummary.research_gap_suggestion} />
                </div>
              </Card>
            )}

            {/* --- Potential Research Gaps (Outliers) --- */}
            {analysisSummary.outlier_documents && analysisSummary.outlier_documents.length > 0 && (
                <Card>
                    <div className="card-body">
                        <Title level="h4">Potential Research Gaps & Emerging Areas</Title>
                        <Paragraph className="t-text-color-secondary">
                            The following documents were identified as "outliers" because their content is unique and does not fit into any of the main research themes. They may represent niche topics, new concepts, or potential research gaps.
                        </Paragraph>
                        <Collapse>
                            <Panel header={`View all ${analysisSummary.outlier_documents_count} outlier documents`}>
                                <List>
                                    {analysisSummary.outlier_documents.map((doc, index) => (
                                        <List.ListItem key={index}>
                                            <Text mark>[{doc.metadata.source}, Page: {doc.metadata.page_number || 'N/A'}]</Text> {doc.text}
                                        </List.ListItem>
                                    ))}
                                </List>
                            </Panel>
                        </Collapse>
                    </div>
                </Card>
            )}

            {/* --- Core Research Themes --- */}
            <Card>
                <div className="card-body">
                    <Title level="h4">Core Research Themes</Title>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--spacing-5)', marginTop: 'var(--spacing-4)' }}>
                        {mainTopics.map(topic => (
                            <Card key={topic.Topic} style={{ minWidth: '300px', flex: 1 }}>
                                <div className="card-body">
                                    <Title level="h5">{formatTopicName(topic.Name)}</Title>
                                    <Paragraph className="t-text-color-secondary">
                                        <Tag theme="primary" variant="light">{topic.Count} documents</Tag>
                                    </Paragraph>
                                    <div style={{ marginTop: 'var(--spacing-3)' }}>
                                        {topic.Representation.slice(0, 5).map((keyword, i) => (
                                            <Tag key={i} style={{ marginRight: 4, marginBottom: 4 }}>{keyword}</Tag>
                                        ))}
                                    </div>
                                </div>
                            </Card>
                        ))}
                    </div>
                    <div style={{ marginTop: 'var(--spacing-4)' }}>
                      <Table
                        rowKey="Topic"
                        data={analysisSummary.topics}
                        columns={[
                          { colKey: 'Topic', title: 'Topic ID', cell: ({ row }: any) => <Tag theme={row.Topic === -1 ? 'default' : 'primary'} variant="light">{row.Topic === -1 ? `Noise Topic` : `Topic ${row.Topic}`}</Tag> },
                          { colKey: 'Name', title: 'Topic Keywords', cell: ({ row }: any) => formatTopicName(row.Name) },
                          { colKey: 'Count', title: 'Document Count' },
                        ] as any}
                        bordered
                        stripe
                      />
                    </div>
                </div>
            </Card>

            {/* --- Topic Trend Analysis --- */}
            <Card>
              <div className="card-body">
                <Title level="h4">Topic Trend Analysis</Title>
                {analysisSummary.trends && analysisSummary.trends.length > 0 ? (
                  renderTrendChart(analysisSummary.trends, analysisSummary.topics)
                ) : (
                  <Alert theme="warning" message="No trend data available" />
                )}
              </div>
            </Card>
        </div>
      )}

      {taskRecord?.status === 'FAILURE' && (
        <Alert theme="error" title="Task Failed" message={
            typeof taskRecord.result === 'string'
            ? taskRecord.result
            : JSON.stringify(taskRecord.result, null, 2)
        } style={{ marginTop: 20 }} />
      )}
    </div>
  );
};

export default GapAnalysisPage;
