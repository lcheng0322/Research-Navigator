import { useState, useEffect } from 'react';
import { Button, Card, Alert, Loading, List, Typography, Textarea, Tag, MessagePlugin, Drawer, Popconfirm, Tabs, Statistic, Progress } from 'tdesign-react';
import { HistoryIcon, DeleteIcon } from 'tdesign-icons-react';
import apiClient from '../services/api';
import { saveAs } from 'file-saver';

const { Title, Paragraph, Text } = Typography;
const { TabPanel } = Tabs;

const SESSION_STORAGE_KEY = 'queryPage_lastState';

const getInitialState = () => {
  const savedState = sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (savedState) {
    try {
      return JSON.parse(savedState);
    } catch (e) {
      console.error("Failed to parse saved state:", e);
      return { query: '', queryResult: null };
    }
  }
  return { query: '', queryResult: null };
};

const QueryPage = () => {
  const { query: initialQuery, queryResult: initialQueryResult } = getInitialState();
  const [query, setQuery] = useState(initialQuery);
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [queryResult, setQueryResult] = useState<any>(initialQueryResult);

  const [historyVisible, setHistoryVisible] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const fetchHistory = async () => {
    setHistoryLoading(true);
    try {
      const response = await apiClient.get('/query/history');
      setHistory(response.data);
    } catch (error) {
      MessagePlugin.error('Failed to load query history.');
      console.error(error);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const handleQuery = async () => {
    if (!query.trim()) return;
    setQueryLoading(true);
    setQueryError(null);
    setQueryResult(null);

    const params = new URLSearchParams();
    params.append('query', query);

    try {
      const response = await apiClient.post('/query/', params, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      });
      const newResult = response.data;
      setQueryResult(newResult);

      const stateToSave = {
        query,
        queryResult: newResult,
      };
      sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(stateToSave));

      MessagePlugin.success('Query completed successfully!');
      fetchHistory(); // Refresh history after a successful query
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || 'Failed to execute query. Please try again.';
      setQueryError(errorMessage);
      MessagePlugin.error(errorMessage);
      console.error(err);
    } finally {
      setQueryLoading(false);
    }
  };

  const handleHistoryItemClick = (item: any) => {
    setQuery(item.query_text);
    if (item.result_payload) {
      try {
        const result = typeof item.result_payload === 'string'
          ? JSON.parse(item.result_payload)
          : item.result_payload;
        setQueryResult(result);
      } catch (e) {
        console.error('Failed to parse history result payload:', e);
        MessagePlugin.error('Failed to load history item. The data might be corrupted.');
        setQueryResult(null); // Clear previous result on error
      }
    } else {
      setQueryResult(null); // Clear result if no payload
      MessagePlugin.info('This history item does not have a saved result. You can run the query again.');
    }
    setHistoryVisible(false);
  };

  const handleDeleteHistoryItem = async (historyId: number) => {
    try {
        await apiClient.delete(`/query/history/${historyId}`);
        MessagePlugin.success('History entry deleted.');
        setHistory(history.filter(item => item.id !== historyId));
    } catch (error) {
        MessagePlugin.error('Failed to delete history entry.');
        console.error(error);
    }
  };

  const handleDownloadDocx = async () => {
    if (!queryResult) return;
    try {
      const response = await apiClient.post('/query/download', {
        query_text: query,
        result_payload: queryResult,
      }, { responseType: 'blob' });

      const blob = new Blob([response.data], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      saveAs(blob, 'smart_qa_result.docx');
      MessagePlugin.success('DOCX generated successfully.');
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Failed to export DOCX.';
      MessagePlugin.error(msg);
      console.error(err);
    }
  };


  return (
    <div className="animate-fadeIn">
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title">Smart Query</h1>
          <p className="page-subtitle">Ask a question to your knowledge base</p>
        </div>
        <Button theme="default" icon={<HistoryIcon />} onClick={() => setHistoryVisible(true)}>
          History
        </Button>
      </div>

      <Card className="card">
        <div className="card-body">
          <form onSubmit={(e) => { e.preventDefault(); handleQuery(); }}>
            <div className="input-group">
              <label htmlFor="query-textarea" className="input-label">Ask a question:</label>
              <Textarea
                id="query-textarea"
                className="input"
                value={query}
                onChange={(value) => setQuery(String(value))}
                placeholder="e.g., What are the main challenges in recovering phosphorus from sewage sludge?"
                autosize={{ minRows: 3 }}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--spacing-4)' }}>
              <Button
                type="submit"
                theme="primary"
                className="btn btn-primary"
                loading={queryLoading}
                disabled={queryLoading || !query.trim()}
              >
                {queryLoading ? 'Querying...' : 'Submit Query'}
              </Button>
            </div>
          </form>
        </div>
      </Card>

      {queryLoading && <Loading text="Querying..." style={{ marginTop: 20 }} />}
      {queryError && <Alert message={queryError} theme="error" style={{ marginTop: 20 }} />}

      {queryResult && (
        <Card className="card" style={{ marginTop: 20 }} actions={<Button theme="primary" variant="outline" onClick={handleDownloadDocx} className="btn btn-secondary">Download as DOCX</Button>}>          <div className="card-body">
            <Tabs defaultValue="answer">
              <TabPanel value="answer" label="Synthesized Answer">
                <div style={{ padding: '16px' }}>
                  {queryResult.reasoned_answer?.result?.confidence_score && (
                    <div style={{ marginBottom: '16px' }}>
                      <Title level="h6">Confidence Score</Title>
                      <Progress theme="plump" percentage={queryResult.reasoned_answer.result.confidence_score * 100} />
                    </div>
                  )}
                  <Title level="h5">Synthesized Answer</Title>
                  <Paragraph>{queryResult.reasoned_answer?.result?.synthesized_answer || 'No answer available.'}</Paragraph>

                  <Title level="h5">Limitations</Title>
                  <Paragraph>{queryResult.reasoned_answer?.result?.limitations_analysis || 'No limitations analysis available.'}</Paragraph>

                  {(queryResult.reasoned_answer?.result?.alternative_hypotheses?.length > 0) && (
                    <>
                      <Title level="h5">Alternative Hypotheses</Title>
                      <List>
                        {(queryResult.reasoned_answer.result.alternative_hypotheses).map((hypo: string, index: number) => (
                          <List.ListItem key={index}>{hypo}</List.ListItem>
                        ))}
                      </List>
                    </>
                  )}
                </div>
              </TabPanel>

              <TabPanel value="analysis" label="Query Analysis">
                <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div style={{display: 'flex', justifyContent: 'space-around'}}>
                    <Statistic title="Intent" value={queryResult.query_analysis?.intent} />
                    <Statistic title="Complexity" value={queryResult.query_analysis?.complexity} />
                    <Statistic title="Domain" value={queryResult.query_analysis?.domain} />
                  </div>
                  <div><Text strong>Rewritten Query:</Text> {queryResult.query_analysis?.rewritten_query}</div>
                  <div><Text strong>Entities:</Text> {(queryResult.query_analysis?.entities || []).map((entity: string, index: number) => <Tag key={index} style={{ marginLeft: 4 }}>{entity}</Tag>)}</div>
                </div>
              </TabPanel>

              <TabPanel value="assessment" label="Evidence Assessment">
                <div style={{ padding: '16px' }}>
                  {queryResult.assessment ? (
                    (() => {
                      const assessWrapper = queryResult.assessment;
                      const isSuccessful = assessWrapper.assessment_successful;
                      const assess = assessWrapper.assessment;

                      if (!isSuccessful || !assess) {
                        return <Alert theme="warning" message={assessWrapper.error || 'Assessment unavailable or failed.'} />;
                      }

                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                          <div>
                            <p><strong>Overall Summary:</strong> {assess.overall_consistency_summary || 'No summary available.'}</p>
                          </div>

                          {(assess.consistent_points && assess.consistent_points.length > 0) && (
                            <div>
                              <Title level="h6">Consistent Points</Title>
                              <List>
                                {assess.consistent_points.map((pt: string, idx: number) => (
                                  <List.ListItem key={idx}>{pt}</List.ListItem>
                                ))}
                              </List>
                            </div>
                          )}

                          {(assess.conflicting_points && assess.conflicting_points.length > 0) && (
                            <div>
                              <Title level="h6">Conflicting Points</Title>
                              <List>
                                {assess.conflicting_points.map((pt: string, idx: number) => (
                                  <List.ListItem key={idx}>{pt}</List.ListItem>
                                ))}
                              </List>
                            </div>
                          )}

                          {(assess.source_quality_assessments && assess.source_quality_assessments.length > 0) && (
                            <div>
                              <Title level="h6">Source Quality Assessments</Title>
                              <List>
                                {assess.source_quality_assessments.map((sq: any, idx: number) => (
                                  <List.ListItem key={idx}>
                                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                                      <Text><strong>{sq.source_id}</strong></Text>
                                      <Text>Relevance: {sq.relevance}</Text>
                                      <Text>Trustworthiness: {sq.trustworthiness}</Text>
                                      <Text>Timeliness: {sq.timeliness}</Text>
                                      <Text>Authority: {sq.authority}</Text>
                                      <Text theme="secondary">{sq.justification}</Text>
                                    </div>
                                  </List.ListItem>
                                ))}
                              </List>
                            </div>
                          )}
                        </div>
                      );
                    })()
                  ) : <p>No assessment available.</p>}
                </div>
              </TabPanel>


              <TabPanel value="context" label="Retrieved Context">
                <div style={{ padding: '16px' }}>
                  {(() => {
                    const citationIndex = queryResult.reasoned_answer?.citation_index || [];
                    const srcfileToId: Record<string, string> = {};
                    citationIndex.forEach((entry: any) => {
                      if (entry?.source_file && entry?.source_id) {
                        srcfileToId[entry.source_file] = entry.source_id;
                      }
                    });
                    return (
                      <List>
                        {queryResult.context?.map((item: any, index: number) => {
                          const file = item.metadata?.source || 'Unknown Source';
                          const sourceId = item.source_id || srcfileToId[file] || 'Source_?';
                          const page = item.metadata?.page_number || 'N/A';
                          return (
                            <List.ListItem key={index}>
                              <Text mark>[{sourceId}, {item.metadata?.title || 'No Title'}, Page {page}]</Text> {item.content}
                            </List.ListItem>
                          );
                        })}
                      </List>
                    );
                  })()}
                </div>
              </TabPanel>
            </Tabs>
          </div>
        </Card>
      )}

      <Drawer header="Query History" visible={historyVisible} onClose={() => setHistoryVisible(false)} placement="right" size="400px">
        {historyLoading ? (
          <Loading text="Loading history..." />
        ) : (
          <List>
            {history.map((item) => (
              <List.ListItem key={item.id}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <div onClick={() => handleHistoryItemClick(item)} style={{ cursor: 'pointer', flex: 1, minWidth: 0 }}>
                        <Text ellipsis>{item.query_text}</Text>
                        <Text theme="secondary" className="text-sm">{new Date(item.created_at).toLocaleString()}</Text>
                    </div>
                    <Popconfirm content="Are you sure you want to delete this entry?" onConfirm={() => handleDeleteHistoryItem(item.id)}>
                        <Button shape="circle" variant="text" theme="danger" icon={<DeleteIcon />} />
                    </Popconfirm>
                </div>
              </List.ListItem>
            ))}
          </List>
        )}
      </Drawer>
    </div>
  );
};

export default QueryPage;
