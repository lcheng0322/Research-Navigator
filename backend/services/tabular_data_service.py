import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, List

import plotly.express as px
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.preprocessing import LabelEncoder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TabularDataService:
    """
    A service to handle processing and advanced analysis of tabular data files (CSV, Excel).
    """

    def _get_dataframe(self, file_path: Path) -> pd.DataFrame:
        """Reads a file into a pandas DataFrame."""
        if file_path.suffix.lower() == '.csv':
            return pd.read_csv(file_path)
        elif file_path.suffix.lower() in ['.xls', '.xlsx']:
            return pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

    def get_basic_info(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Returns basic information about the dataframe."""
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "column_names": df.columns.tolist(),
            "numeric_columns": numeric_cols,
            "categorical_columns": categorical_cols,
            "missing_values": {k: int(v) for k, v in df.isnull().sum().to_dict().items() if v > 0}
        }

    def get_descriptive_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generates descriptive statistics for both numeric and categorical columns."""
        numeric_stats = df.describe(include='number').to_dict()
        
        categorical_stats = None
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns
        if not categorical_cols.empty:
            categorical_stats = df.describe(include=['object', 'category']).to_dict()

        return {"numeric": numeric_stats, "categorical": categorical_stats}

    def perform_linear_regression(self, df: pd.DataFrame, independent_var: str, dependent_var: str) -> Optional[Dict[str, Any]]:
        """Performs a single linear regression."""
        try:
            temp_df = df[[independent_var, dependent_var]].dropna()
            if len(temp_df) < 2: return None

            X = temp_df[[independent_var]].values
            y = temp_df[dependent_var].values
            model = LinearRegression().fit(X, y)
            
            return {
                'type': 'Linear',
                'dependent_variable': dependent_var,
                'independent_variable': independent_var,
                'coefficient': model.coef_[0],
                'intercept': model.intercept_,
                'r_squared': model.score(X, y)
            }
        except Exception as e:
            logging.warning(f"Could not perform linear regression for {independent_var} vs {dependent_var}: {e}")
            return None

    def perform_logistic_regression(self, df: pd.DataFrame, independent_vars: List[str], dependent_var: str) -> Optional[Dict[str, Any]]:
        """Performs logistic regression for a categorical dependent variable."""
        try:
            cols_to_use = independent_vars + [dependent_var]
            temp_df = df[cols_to_use].dropna()
            if len(temp_df) < 2 or temp_df[dependent_var].nunique() < 2:
                return None

            X = pd.get_dummies(temp_df[independent_vars], drop_first=True)
            le = LabelEncoder()
            y = le.fit_transform(temp_df[dependent_var])

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
            model = LogisticRegression(max_iter=1000).fit(X_train, y_train)
            
            return {
                'type': 'Logistic',
                'dependent_variable': dependent_var,
                'independent_variables': independent_vars,
                'accuracy': accuracy_score(y_test, model.predict(X_test)),
                'class_names': le.classes_.tolist(),
                'confusion_matrix': confusion_matrix(y_test, model.predict(X_test)).tolist()
            }
        except Exception as e:
            logging.warning(f"Could not perform logistic regression for {dependent_var}: {e}")
            return None

    def generate_visualizations(self, df: pd.DataFrame, vis_type: str, x_col: str, y_col: Optional[str] = None) -> Optional[str]:
        """Generates a specified type of visualization."""
        try:
            if vis_type == 'histogram' and x_col in df.columns:
                fig = px.histogram(df, x=x_col, title=f"Histogram of {x_col}")
            elif vis_type == 'scatter' and x_col in df.columns and y_col in df.columns:
                fig = px.scatter(df, x=x_col, y=y_col, title=f"Scatter Plot of {y_col} vs {x_col}")
            elif vis_type == 'boxplot' and x_col in df.columns:
                fig = px.box(df, y=x_col, title=f"Box Plot of {x_col}")
            else:
                return None
            return fig.to_json()
        except Exception as e:
            logging.warning(f"Could not generate {vis_type} for columns {x_col}, {y_col}: {e}")
            return None

    def get_full_analysis(self, file_path: Path) -> Dict[str, Any]:
        """
        Reads a tabular file and performs a comprehensive analysis, exposing building blocks for API control.
        """
        logging.info(f"Performing full analysis on tabular file: {file_path}")
        try:
            df = self._get_dataframe(file_path)
            
            # 1. Get Basic Info
            basic_info = self.get_basic_info(df)
            
            # 2. Get Descriptive Statistics
            stats = self.get_descriptive_statistics(df)
            
            # 3. Get Correlation Matrix
            correlation_matrix = None
            if len(basic_info['numeric_columns']) > 1:
                correlation_matrix = df[basic_info['numeric_columns']].corr().to_dict()

            # The API layer will now be responsible for calling the regression and visualization
            # methods based on user input, using the info provided by this initial analysis.
            
            analysis_result = {
                "file_info": basic_info,
                "descriptive_statistics": stats,
                "correlation_matrix": correlation_matrix,
            }
            
            logging.info(f"Successfully generated base analysis for {file_path.name}")
            return analysis_result

        except Exception as e:
            logging.error(f"Failed to analyze tabular file {file_path}. Error: {e}", exc_info=True)
            raise

# Singleton instance
tabular_data_service = TabularDataService()
