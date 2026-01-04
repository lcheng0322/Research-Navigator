import { useState } from 'react';
import { Upload, MessagePlugin, Card, Tabs, Statistic, Tag, Table, Alert, Button, Form, Select } from 'tdesign-react';
import type { UploadFile } from 'tdesign-react';
import Plot from 'react-plotly.js';
import apiClient from '../services/api';

const { TabPanel } = Tabs;
const { FormItem } = Form;
const { Option } = Select;

const TabularDataAnalysisPage = () => {
  const [selectedFile, setSelectedFile] = useState<UploadFile | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [baseAnalysis, setBaseAnalysis] = useState<any>(null);
  const [fileId, setFileId] = useState<string | null>(null);

  const [regressionResult, setRegressionResult] = useState<any>(null);
  const [visResult, setVisResult] = useState<any>(null);

  const [form] = Form.useForm();

  const handleFileChange = (files: UploadFile[]) => {
    if (files && files.length > 0) {
      setSelectedFile(files[0]);
      setBaseAnalysis(null);
      setFileId(null);
      setRegressionResult(null);
      setVisResult(null);
      setError(null);
    } else {
      setSelectedFile(null);
    }
  };

  const handleInitialAnalyze = async () => {
    if (!selectedFile || !selectedFile.raw) {
      MessagePlugin.error('No file selected or file is empty.');
      return;
    }
    setIsLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append('file', selectedFile.raw);

    try {
      const response = await apiClient.post('/analyze/tabular-data/initiate', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setBaseAnalysis(response.data);
      setFileId(response.data.file_id);
      MessagePlugin.success('Initial analysis completed successfully!');
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || 'Failed to analyze file.';
      setError(errorMessage);
      MessagePlugin.error(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  const onRegressionSubmit: (values: any) => Promise<void> = async (values) => {
    if (!fileId) return;
    setIsLoading(true);
    setRegressionResult(null);
    const params = new URLSearchParams();
    params.append('file_id', fileId);
    params.append('analysis_type', values.analysis_type);
    params.append('dependent_var', values.dependent_var);
    values.independent_vars.forEach((v: string) => params.append('independent_vars', v));

    try {
      const response = await apiClient.post('/analyze/tabular-data/regression', params);
      setRegressionResult(response.data);
      MessagePlugin.success('Regression analysis completed!');
    } catch (err: any) {
      MessagePlugin.error(err.response?.data?.detail || 'Regression failed.');
    } finally {
      setIsLoading(false);
    }
  };

  const onVisSubmit: (values: any) => Promise<void> = async (values) => {
    if (!fileId) return;
    setIsLoading(true);
    setVisResult(null);
    const params = new URLSearchParams();
    params.append('file_id', fileId);
    params.append('vis_type', values.vis_type);
    params.append('x_col', values.x_col);
    if (values.y_col) {
      params.append('y_col', values.y_col);
    }

    try {
      const response = await apiClient.post('/analyze/tabular-data/visualize', params);
      setVisResult(response.data);
      MessagePlugin.success('Visualization generated!');
    } catch (err: any) {
      MessagePlugin.error(err.response?.data?.detail || 'Visualization failed.');
    } finally {
      setIsLoading(false);
    }
  };

  const renderNumericStats = (stats: any) => {
    if (!stats) return null;
    const columns = Object.keys(stats).map(col => ({ colKey: col, title: col }));
    const data = Object.keys(stats[Object.keys(stats)[0]] || {}).map(index => {
        const row: { [key: string]: any } = { stat: index };
        Object.keys(stats).forEach(col => {
            row[col] = stats[col][index]?.toFixed(3) ?? 'N/A';
        });
        return row;
    });
    const statColumn = { colKey: 'stat', title: 'Statistic' };
    return <Table rowKey="stat" data={data} columns={[statColumn, ...columns]} bordered stripe />;
  };

  const renderCategoricalStats = (stats: any) => {
    if (!stats) return <p>No categorical data to analyze.</p>;
    const columns = Object.keys(stats).map(col => ({ colKey: col, title: col }));
    const data = Object.keys(stats[Object.keys(stats)[0]] || {}).map(index => {
        const row: { [key: string]: any } = { stat: index };
        Object.keys(stats).forEach(col => {
            row[col] = stats[col][index] ?? 'N/A';
        });
        return row;
    });
    const statColumn = { colKey: 'stat', title: 'Statistic' };
    return <Table rowKey="stat" data={data} columns={[statColumn, ...columns]} bordered stripe />;
  };

  return (
    <div className="animate-fadeIn">
      <div className="page-header">
        <h1 className="page-title">Interactive Tabular Data Analysis</h1>
        <p className="page-subtitle">Upload a file, perform initial analysis, then run custom regressions and visualizations.</p>
      </div>

      <Card className="card">
        <div className="card-body">
            <div className="input-group">
                <label className="input-label">1. Upload Data File</label>
                <Upload onChange={handleFileChange} theme="custom" accept=".csv,.xlsx" autoUpload={false} showUploadProgress={false} className="input">
                    <Button theme="default" className="btn">Select CSV/XLSX File</Button>
                </Upload>
                {selectedFile && <p className="input-help">Selected: {selectedFile.name}</p>}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--spacing-4)' }}>
                <Button onClick={handleInitialAnalyze} loading={isLoading} disabled={!selectedFile || !!baseAnalysis} className="btn btn-primary">
                    {baseAnalysis ? 'Analysis Complete' : 'Run Initial Analysis'}
                </Button>
            </div>
        </div>
      </Card>

      {error && <Alert theme="error" message={error} style={{ marginTop: 20 }} />}

      {baseAnalysis && (
        <Tabs defaultValue="overview" style={{ marginTop: 20 }}>
          <TabPanel value="overview" label="Data Overview">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-6)' }}>
                <Statistic title="Row Count" value={baseAnalysis.file_info.row_count} />
                <Statistic title="Column Count" value={baseAnalysis.file_info.column_count} />
                <div><h3 className="page-title">Columns</h3>{baseAnalysis.file_info.column_names.map((col: string) => <Tag key={col} style={{margin: '2px'}}>{col}</Tag>)}</div>
            </div>
          </TabPanel>
          <TabPanel value="stats" label="Descriptive Statistics">
            <Tabs>
              <TabPanel value="numeric" label="Numeric">{renderNumericStats(baseAnalysis.descriptive_statistics.numeric)}</TabPanel>
              <TabPanel value="categorical" label="Categorical">{renderCategoricalStats(baseAnalysis.descriptive_statistics.categorical)}</TabPanel>
            </Tabs>
          </TabPanel>
          <TabPanel value="interactive" label="Interactive Analysis">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
              <Card title="Regression Analysis">
                <Form form={form} onSubmit={({ validateResult }) => { if (validateResult === true) onRegressionSubmit(form.getFieldsValue(true)); }} layout="vertical">
                  <FormItem label="Analysis Type" name="analysis_type"><Select><Option key="linear" value="linear">Linear</Option><Option key="logistic" value="logistic">Logistic</Option></Select></FormItem>
                  <FormItem label="Dependent Variable" name="dependent_var"><Select>{baseAnalysis.file_info.column_names.map((c: string) => <Option key={c} value={c}>{c}</Option>)}</Select></FormItem>
                  <FormItem label="Independent Variables" name="independent_vars"><Select multiple>{baseAnalysis.file_info.column_names.map((c: string) => <Option key={c} value={c}>{c}</Option>)}</Select></FormItem>
                  <Button theme="primary" type="submit" loading={isLoading}>Run Regression</Button>
                </Form>
                {regressionResult && <pre style={{marginTop: 16, background: '#f5f5f5', padding: 12}}>{JSON.stringify(regressionResult, null, 2)}</pre>}
              </Card>
              <Card title="Generate Visualization">
                <Form onSubmit={({ validateResult }) => { if (validateResult === true) onVisSubmit(form.getFieldsValue(true)); }} layout="vertical">
                  <FormItem label="Visualization Type" name="vis_type"><Select><Option key="histogram" value="histogram">Histogram</Option><Option key="scatter" value="scatter">Scatter Plot</Option><Option key="boxplot" value="boxplot">Box Plot</Option></Select></FormItem>
                  <FormItem label="X-Axis Column" name="x_col"><Select>{baseAnalysis.file_info.column_names.map((c: string) => <Option key={c} value={c}>{c}</Option>)}</Select></FormItem>
                  <FormItem label="Y-Axis Column (for Scatter)" name="y_col"><Select>{baseAnalysis.file_info.column_names.map((c: string) => <Option key={c} value={c}>{c}</Option>)}</Select></FormItem>
                  <Button theme="primary" type="submit" loading={isLoading}>Generate Plot</Button>
                </Form>
                {visResult && <Plot data={visResult.data} layout={visResult.layout} />}
              </Card>
            </div>
          </TabPanel>
        </Tabs>
      )}
    </div>
  );
};

export default TabularDataAnalysisPage;
