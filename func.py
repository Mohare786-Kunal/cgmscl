import json
import io
import os
import re
import urllib3
from fdk import response

# OCI SDK imports
import oci
from oci.generative_ai_inference import GenerativeAiInferenceClient
from oci.generative_ai_inference.models import (
    ChatDetails,
    OnDemandServingMode,
    CohereChatRequest
)

# Import exact system prompts from prompts.py
from prompts import SQL_GENERATION_PROMPT, RESPONSE_GENERATION_PROMPT

# Initialize HTTP client
http = urllib3.PoolManager()

# Configuration from environment variables
SQL_ENDPOINT = os.environ.get('SQL_ENDPOINT', 'http://80.225.197.97:8000/runsql')
OCI_COMPARTMENT_ID = os.environ.get('OCI_COMPARTMENT_ID', 'ocid1.tenancy.oc1..aaaaaaaaj5e33qgh3bwtsw27myq7sfuwsxdn5wi5c7uthylt6lhcx2go2wtq')
MODEL_ID = "cohere.command-a-03-2025"  # Using Cohere Command R Plus model

# Initialize OCI Generative AI client
def get_generative_ai_client():
    """Initialize OCI Generative AI client with resource principal authentication"""
    try:
        # Use resource principal for OCI Functions
        signer = oci.auth.signers.get_resource_principals_signer()
        return GenerativeAiInferenceClient(
            config={},
            signer=signer,
            service_endpoint="https://inference.generativeai.ap-hyderabad-1.oci.oraclecloud.com"
        )
    except Exception as e:
        print(f"Error initializing OCI client with resource principal: {str(e)}")
        # Fallback to config file authentication for local testing
        config = oci.config.from_file()
        return GenerativeAiInferenceClient(
            config=config,
            service_endpoint="https://inference.generativeai.ap-hyderabad-1.oci.oraclecloud.com"
        )

def handler(ctx, data: io.BytesIO = None):
    """OCI Functions handler - main entry point"""
    try:
        # Parse incoming request
        try:
            body = json.loads(data.getvalue().decode('utf-8'))
        except Exception as e:
            return response.Response(
                ctx,
                response_data=json.dumps({'error': 'Invalid JSON in request body'}),
                headers={"Content-Type": "application/json"}
            )
        
        user_query = body.get('query', '').strip()
        
        if not user_query:
            return response.Response(
                ctx,
                response_data=json.dumps({'error': 'Missing required field: query'}),
                headers={"Content-Type": "application/json"}
            )
        
        print(f"User query: {user_query}")
        
        # Step 1: Generate SQL from natural language query
        sql_query = generate_sql(user_query)
        print(f"Generated SQL: {sql_query}")
        
        # Step 2: Execute the generated SQL query
        sql_result = execute_sql(sql_query)
        print(f"SQL Execution Result: {sql_result}")
        
        # Step 3: Generate natural language response from data
        llm_result = generate_response(user_query, sql_query, sql_result)
        print(f"LLM Result: {llm_result}")
        
        # Extract response and visualization from LLM result
        if isinstance(llm_result, dict):
            response_text = llm_result.get("response", "")
            visualization = llm_result.get("visualization", {
                "chartType": None,
                "title": "Auto-generated Chart",
                "xAxis": None,
                "yAxis": None,
                "mode": None
            })
            
            # Handle case where response_text might be a JSON string (double-encoded)
            if isinstance(response_text, str) and response_text.strip().startswith('{'):
                try:
                    inner_parsed = json.loads(response_text)
                    if isinstance(inner_parsed, dict):
                        if "response" in inner_parsed:
                            response_text = inner_parsed.get("response", response_text)
                        if "visualization" in inner_parsed and (visualization.get("chartType") is None and visualization.get("xAxis") is None):
                            inner_viz = inner_parsed.get("visualization")
                            if isinstance(inner_viz, dict):
                                visualization = inner_viz
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass
        else:
            response_text = str(llm_result)
            visualization = {
                "chartType": None,
                "title": "Auto-generated Chart",
                "xAxis": None,
                "yAxis": None,
                "mode": None
            }
        
        # Return the final result
        result = {
            'query': user_query,
            'sql': sql_query,
            'data': sql_result,
            'response': response_text,
            'visualization': visualization
        }
        
        return response.Response(
            ctx,
            response_data=json.dumps(result, default=str),
            headers={
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Methods": "*"
            }
        )
    
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return response.Response(
            ctx,
            response_data=json.dumps({'error': 'Internal server error', 'details': str(e)}),
            headers={"Content-Type": "application/json"}
        )

def generate_sql(user_query):
    """Generate SQL query from natural language using Cohere Command model"""
    
    user_message = f"User Question: {user_query}\n\nReturn ONLY raw Oracle SQL:"
    
    try:
        # Initialize Generative AI client
        gen_ai_client = get_generative_ai_client()
        
        # Create chat request for Cohere using EXACT prompt from lambda_K.py
        chat_request = ChatDetails(
            compartment_id=OCI_COMPARTMENT_ID,
            serving_mode=OnDemandServingMode(model_id=MODEL_ID),
            chat_request=CohereChatRequest(
                message=user_message,
                preamble_override=SQL_GENERATION_PROMPT,
                max_tokens=512,
                temperature=0.3,
                top_p=1.0,
                is_stream=False
            )
        )
        
        # Invoke the model
        chat_response = gen_ai_client.chat(chat_request)
        
        # Extract the generated SQL
        output_text = chat_response.data.chat_response.text.strip()
        
        # Clean up the output (same logic as lambda_K.py)
        sql = output_text.replace("```sql", "").replace("```", "").strip().rstrip(";")
        sql = re.sub(r'=\s*"([^"]+)"', r"= '\1'", sql)
        
        return sql
        
    except Exception as e:
        print(f"Error generating SQL: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

def execute_sql(sql_query):
    """Execute SQL query via HTTP endpoint"""
    try:
        sql_payload = {"sql": sql_query}
        
        # Forward SQL to endpoint
        http_response = http.request(
            "POST",
            SQL_ENDPOINT,
            body=json.dumps(sql_payload),
            headers={"Content-Type": "application/json"},
            timeout=30.0
        )
        
        result = json.loads(http_response.data.decode("utf-8"))
        return result
    
    except Exception as e:
        print(f"Error executing SQL: {str(e)}")
        return {"error": f"SQL execution failed: {str(e)}"}

def count_tokens(text):
    """Approximate token count (4 characters per token)"""
    return len(text) // 4

def truncate_sql_result(sql_result, top_n=20, bottom_n=20):
    """Truncate SQL result to top N and bottom N rows"""
    try:
        if isinstance(sql_result, dict) and "error" in sql_result:
            return sql_result
        
        rows = None
        if isinstance(sql_result, list):
            rows = sql_result
        elif isinstance(sql_result, dict):
            if "rows" in sql_result:
                rows = sql_result["rows"]
            elif "data" in sql_result:
                rows = sql_result["data"]
            elif "results" in sql_result:
                rows = sql_result["results"]
            else:
                rows = [sql_result]
        
        if rows is None or not isinstance(rows, list):
            return sql_result
        
        total_rows = len(rows)
        
        if total_rows <= (top_n + bottom_n):
            return sql_result
        
        top_rows = rows[:top_n]
        bottom_rows = rows[-bottom_n:]
        
        if isinstance(sql_result, list):
            truncated_result = top_rows + bottom_rows
        elif isinstance(sql_result, dict):
            truncated_result = sql_result.copy()
            if "rows" in truncated_result:
                truncated_result["rows"] = top_rows + bottom_rows
            elif "data" in truncated_result:
                truncated_result["data"] = top_rows + bottom_rows
            elif "results" in truncated_result:
                truncated_result["results"] = top_rows + bottom_rows
            else:
                truncated_result = top_rows + bottom_rows
        else:
            truncated_result = top_rows + bottom_rows
        
        if isinstance(truncated_result, dict):
            truncated_result["_truncated"] = True
            truncated_result["_total_rows"] = total_rows
            truncated_result["_top_rows_shown"] = top_n
            truncated_result["_bottom_rows_shown"] = bottom_n
        else:
            truncated_result = {
                "rows": truncated_result,
                "_truncated": True,
                "_total_rows": total_rows,
                "_top_rows_shown": top_n,
                "_bottom_rows_shown": bottom_n
            }
        
        return truncated_result
        
    except Exception as e:
        print(f"Error truncating SQL result: {str(e)}")
        return sql_result

def get_truncated_system_prompt():
    """Get truncated context to prepend to system prompt"""
    return """## CRITICAL CONTEXT - TRUNCATED DATA ANALYSIS:

**IMPORTANT**: The data provided below contains ONLY the **top 20 rows and bottom 20 rows** from the full SQL query result. The complete dataset is too large to process in a single analysis.

**Your Analysis Should:**
- Analyze the provided top 20 and bottom 20 rows
- Keep the same format and structure as you would for a full analysis
- Clearly indicate in your response that this is an analysis of the top 20 and bottom 20 rows
- Mention that the full dataset is available in a downloadable Excel file for complete data review
- Provide insights based on the sample data while acknowledging the limitation

**Response Format:**
- Start your response with a note: "Below is the analysis of the top 20 and bottom 20 rows from the query results. For the complete dataset, please refer to the downloadable Excel file."
- Maintain the same professional format and table structure as you would for full data
- Include all provided rows in your analysis
- Provide meaningful insights based on the sample data

"""

def generate_response(user_query, sql_query, sql_result):
    """Generate natural language response using Cohere Command model"""
    
    # Format the query results
    formatted_results = json.dumps(sql_result, indent=2, default=str)
    
    # Count tokens
    token_count = count_tokens(formatted_results)
    print(f"Token count of SQL result: {token_count}")
    
    TOKEN_THRESHOLD = 185000
    is_truncated = False
    truncated_result = sql_result
    
    if token_count > TOKEN_THRESHOLD:
        print(f"Token count ({token_count}) exceeds threshold. Truncating data...")
        truncated_result = truncate_sql_result(sql_result, top_n=20, bottom_n=20)
        formatted_results = json.dumps(truncated_result, indent=2, default=str)
        is_truncated = True
        print(f"Data truncated. New token count: {count_tokens(formatted_results)}")
    
    # Select system prompt based on truncation
    if is_truncated:
        system_prompt_to_use = get_truncated_system_prompt() + RESPONSE_GENERATION_PROMPT
    else:
        system_prompt_to_use = RESPONSE_GENERATION_PROMPT
    
    user_message = f"""DATA ANALYSIS TASK

User Question: {user_query}

SQL Query Executed: {sql_query}

Query Results:
{formatted_results}

Based on the above data, provide a clear and helpful response to the user's question.

**CRITICAL**: You MUST return your response as a valid JSON object with exactly two fields: "response" (your analysis as markdown text) and "visualization" (the visualization configuration object). Return ONLY the JSON object, no additional text before or after."""

    try:
        gen_ai_client = get_generative_ai_client()
        
        # Create chat request using EXACT prompt from lambda_K.py
        chat_request = ChatDetails(
            compartment_id=OCI_COMPARTMENT_ID,
            serving_mode=OnDemandServingMode(model_id=MODEL_ID),
            chat_request=CohereChatRequest(
                message=user_message,
                preamble_override=system_prompt_to_use,
                max_tokens=2000,
                temperature=0.3,
                top_p=0.9,
                is_stream=False
            )
        )
        
        chat_response = gen_ai_client.chat(chat_request)
        output_text = chat_response.data.chat_response.text.strip()
        
        # Parse JSON response (same logic as lambda_K.py)
        try:
            cleaned_text = output_text
            if "```json" in cleaned_text:
                cleaned_text = cleaned_text.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned_text:
                cleaned_text = cleaned_text.split("```")[1].split("```")[0].strip()
            
            parsed_response = json.loads(cleaned_text)
            
            if isinstance(parsed_response, dict):
                response_text = parsed_response.get("response", output_text)
                visualization = parsed_response.get("visualization", None)
                
                # Handle case where response_text might be a JSON string that needs parsing
                if isinstance(response_text, str) and response_text.strip().startswith('{'):
                    try:
                        inner_parsed = json.loads(response_text)
                        if isinstance(inner_parsed, dict) and "response" in inner_parsed:
                            response_text = inner_parsed.get("response", response_text)
                            if "visualization" in inner_parsed and visualization is None:
                                visualization = inner_parsed.get("visualization")
                    except (json.JSONDecodeError, ValueError):
                        pass
                
                # Validate visualization structure
                if visualization is not None and isinstance(visualization, dict):
                    default_viz = {
                        "chartType": None,
                        "title": "Auto-generated Chart",
                        "xAxis": None,
                        "yAxis": None,
                        "mode": None
                    }
                    for key in default_viz:
                        if key not in visualization:
                            visualization[key] = default_viz[key]
                else:
                    visualization = {
                        "chartType": None,
                        "title": "Auto-generated Chart",
                        "xAxis": None,
                        "yAxis": None,
                        "mode": None
                    }
                
                return {
                    "response": response_text,
                    "visualization": visualization
                }
            else:
                return {
                    "response": output_text,
                    "visualization": {
                        "chartType": None,
                        "title": "Auto-generated Chart",
                        "xAxis": None,
                        "yAxis": None,
                        "mode": None
                    }
                }
        except json.JSONDecodeError as json_err:
            print(f"Warning: Could not parse LLM response as JSON: {str(json_err)}")
            print(f"Raw response (first 500 chars): {output_text[:500]}...")
            
            return {
                "response": output_text,
                "visualization": {
                    "chartType": None,
                    "title": "Auto-generated Chart",
                    "xAxis": None,
                    "yAxis": None,
                    "mode": None
                }
            }
    
    except Exception as e:
        print(f"Error generating response: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            "response": f"Query executed successfully. Results: {formatted_results}",
            "visualization": {
                "chartType": None,
                "title": "Auto-generated Chart",
                "xAxis": None,
                "yAxis": None,
                "mode": None
            }
        }
