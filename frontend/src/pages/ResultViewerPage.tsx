import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Alert,
  Loading,
  Typography,
  List,
  Table,
  Tag,
  Button,
} from 'tdesign-react';
import type { TableProps } from 'tdesign-react';
import { ArrowLeftIcon } from 'tdesign-icons-react';
import Plot from 'react-plotly.js';
import TaskWatcher from '../components/TaskWatcher';
import useTaskStore from '../store/taskStore';

const { Title, Paragraph, Text } = Typography;

const gapAnalysisColumns: TableProps['columns'] = [
  { colKey: 'Topic', title: 'Topic ID', cell: ({ row }) => <Tag theme={row.Topic === -1 ? 'default' : 'primary'} variant="light">{row.Topic === -1 ? `Noise Topic` : `Topic ${row.Topic}`}</Tag> },
  { colKey: 'Name', title: 'Topic Keywords', cell: ({ row }) => row.Name.split('_').slice(1).join(', ') },
  { colKey: 'Count', title: 'Document Count' },
];

const ResultViewerPage = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const task = useTaskStore((state) => state.tasks.find((t) => t.taskId === taskId));

  const handleBack = () => navigate('/tasks');

  const renderTrendChart = (trends: any[], topics: any[]) => {
    if (!trends || trends.length === 0) return <p>Trend data is not available.</p>;

    const topicNames = topics.reduce((acc, topic) => {
      acc[topic.Topic] = topic.Name.split('_').slice(1).join(', ');
      return acc;
    }, {});

    const data = trends.reduce((acc, trend) => {
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

  const renderSuccess = (result: any) => {
    if (!result) return <Alert theme="info" message="No result available yet" />;

    switch (task?.type) {
      case 'literature-review':
        const review = result;
        return (
          <Card>
            <div className="card-body">
              <Title level="h5">{review.title || 'Generated Literature Review'}</Title>
              {review.content && Object.entries(review.content).map(([section, text]) => (
                <div key={section}>
                  <Title level="h6" style={{ marginTop: 12 }}>{section}</Title>
                  <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{text as string}</Paragraph>
                </div>
              ))}
              {review.references && (
                <>
                  <Title level="h6" style={{ marginTop: 12 }}>References</Title>
                  <List>
                    {Object.entries(review.references)
                      .sort(([aKey], [bKey]) => aKey.localeCompare(bKey, undefined, { numeric: true, sensitivity: 'base' }))
                      .map(([key, value]) => (
                        <List.ListItem key={key}>{`${key}: ${value}`}</List.ListItem>
                      ))}
                  </List>
                </>
              )}
            </div>
          </Card>
        );
      case 'gap-analysis':
        const analysis = result;
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-6)' }}>
            <Card><div className="card-body"><Title level="h5">Analysis Summary</Title><div style={{display: 'flex', justifyContent: 'space-around'}}><Text><strong>Total Documents:</strong> {analysis.total_documents_analyzed}</Text><Text><strong>Core Topics:</strong> {analysis.total_topics_found}</Text></div></div></Card>
            {analysis.research_gap_suggestion && <Alert theme="info" title="Research Direction Suggestion" message={analysis.research_gap_suggestion} />}
            {analysis.topics && <Card><div className="card-body"><Title level="h5">Topics</Title><Table rowKey="Topic" data={analysis.topics} columns={gapAnalysisColumns} bordered stripe /></div></Card>}
            {analysis.trends && <Card><div className="card-body"><Title level="h5">Topic Trend Analysis</Title>{renderTrendChart(analysis.trends, analysis.topics)}</div></Card>}
          </div>
        );
      default:
        return <Card><div className="card-body"><Title level="h5">Raw Result</Title><pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>{JSON.stringify(result, null, 2)}</pre></div></Card>;
    }
  };

  const renderFailure = (error: string) => (
    <Alert theme="error" title="Task Failed" message={error} />
  );

  const renderPending = () => (
    <Alert theme="info" message="Task is pending and will start shortly." />
  );

  const renderStarted = () => (
    <div style={{ textAlign: 'center' }}>
      <Loading size="large" />
      <p style={{ marginTop: '1rem' }}>Task is running, results will be displayed automatically upon completion.</p>
    </div>
  );

  if (!taskId) {
    return (
        <Card><div className="card-body"><Alert theme="error" message="Task ID is required." /><Button onClick={handleBack} style={{ marginTop: 16 }} icon={<ArrowLeftIcon />}>Back to Task Center</Button></div></Card>
    );
  }

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">Task Details: {task?.title || taskId}</h1>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
            <p className="page-subtitle">View the status and results of a specific task.</p>
            <Button variant="outline" icon={<ArrowLeftIcon />} onClick={handleBack} className="btn btn-secondary">Back</Button>
        </div>
      </div>

      {task && (
        <Card className="card" style={{marginBottom: 'var(--spacing-6)'}}>
            <div className="card-body">
                <div style={{display: 'flex', justifyContent: 'space-around', alignItems: 'center'}}>
                    <Text><strong>Task ID:</strong> {task.taskId}</Text>
                    <Text><strong>Type:</strong> {task.type}</Text>
                    <Text><strong>Status:</strong> <Tag theme={task.status === 'SUCCESS' ? 'success' : task.status === 'FAILURE' ? 'danger' : task.status === 'STARTED' ? 'primary' : 'warning'}>{task.status}</Tag></Text>
                    <Text><strong>Created:</strong> {new Date(task.createdAt).toLocaleString()}</Text>
                    {task.completedAt && <Text><strong>Completed:</strong> {new Date(task.completedAt).toLocaleString()}</Text>}
                </div>
            </div>
        </Card>
      )}

      <TaskWatcher
        taskId={taskId}
        onSuccess={renderSuccess}
        onFailure={renderFailure}
        onPending={renderPending}
        onStarted={renderStarted}
      />
    </div>
  );
};

export default ResultViewerPage;
