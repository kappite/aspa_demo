import streamlit as st
import pandas as pd
import snowflake.connector
import openai
from dotenv import load_dotenv
import os
from datetime import date, datetime

# Load environment variables from .env file
load_dotenv()

# Use environment variables
SNOWFLAKE_USER = os.getenv('SNOWFLAKE_USER')
SNOWFLAKE_PASSWORD = os.getenv('SNOWFLAKE_PASSWORD')
SNOWFLAKE_ACCOUNT = os.getenv('SNOWFLAKE_ACCOUNT')
SNOWFLAKE_WAREHOUSE = os.getenv('SNOWFLAKE_WAREHOUSE')
SNOWFLAKE_DATABASE = os.getenv('SNOWFLAKE_DATABASE')
SNOWFLAKE_SCHEMA = os.getenv('SNOWFLAKE_SCHEMA')
AZURE_OPENAI_API_KEY = os.getenv('AZURE_OPENAI_API_KEY')

# Azure OpenAI API configurations
AZURE_OPENAI_ENDPOINT = "https://aoa-ai-demo2.openai.azure.com/"
AZURE_OPENAI_API_VERSION = "2023-12-01-preview"
AZURE_OPENAI_DEPLOYMENT_NAME = "manufacturing-demo"

# Set up OpenAI library to use Azure OpenAI service
openai.api_type = "azure"
openai.api_key = AZURE_OPENAI_API_KEY
openai.api_base = AZURE_OPENAI_ENDPOINT
openai.api_version = AZURE_OPENAI_API_VERSION

# Function to call GPT model on Azure OpenAI
def query_chatgpt(system_prompt, manual_content):
    response = openai.ChatCompletion.create(
        engine=AZURE_OPENAI_DEPLOYMENT_NAME,
        messages=[
            {"role": "system", "content": f"Follow these: {system_prompt}"},
            {"role": "user", "content": f"Use this data: {manual_content}"}
        ],
        max_tokens=1000
    )
    return response['choices'][0]['message']['content']

# Function to connect to Snowflake
def connect_to_snowflake():
    return snowflake.connector.connect(
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        account=SNOWFLAKE_ACCOUNT,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA
    )

# Function to run a query using Snowflake connector
def run_query(query):
    conn = connect_to_snowflake()
    cur = conn.cursor()
    cur.execute(query)
    result = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    df = pd.DataFrame(result, columns=columns)
    cur.close()
    conn.close()
    return df

# Function to fetch the manual content from Snowflake
def fetch_manual(product_code):
    query = f"""
    SELECT ManualContent
    FROM DEMO.ASPA.Manuals
    WHERE ProductCode = '{product_code}'
    """
    result = run_query(query)
    
    # Check and normalize column names
    result.columns = result.columns.str.strip().str.lower()  # Normalize column names

    if not result.empty and 'manualcontent' in result.columns:
        return result.iloc[0]['manualcontent']
    else:
        st.write("No manual found or 'manualcontent' column missing for the product code:", product_code)
        return None

# Function to fetch issue history for a customer with product names
def fetch_issue_history(customer_id, product_code=None):
    query = f"""
    SELECT ih.IssueDate, ih.ProductCode, p.ProductName, ih.IssueDescription, ih.Resolution
    FROM DEMO.ASPA.IssueHistory ih
    JOIN DEMO.ASPA.Product p ON ih.ProductCode = p.ProductCode
    WHERE ih.CustomerID = '{customer_id}'
    """
    if product_code:
        query += f" AND ih.ProductCode = '{product_code}'"

    query += " ORDER BY ih.IssueDate DESC"
    
    return run_query(query)

# Function to display the relevant manual section as a bullet-point list
def show_manual_section(issue_description, manual_text):
    gpt_prompt = f"""
    Based on the following issue description: '{issue_description}', 
    provide the relevant troubleshooting steps from the manual as a bullet point list.

    Manual Content:
    {manual_text}
    """
    gpt_response = query_chatgpt(gpt_prompt, manual_text)
    
    # Split the response into lines
    lines = gpt_response.split("\n")

    # Remove any lines that contain redundant headers or explanations
    formatted_response = []
    for line in lines:
        # Skip lines that repeat the issue description or contain introductory text
        if "troubleshooting steps" in line.lower() or issue_description.lower() in line.lower():
            continue
        elif line.strip():
            # Add valid lines to the response list
            formatted_response.append(line.strip())

    # Return only the formatted bullet-point list
    return "\n".join(formatted_response)

# Function to convert non-serializable fields to serializable ones
def convert_to_serializable(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

# Streamlit app title and description
st.title("Customer Service Demo with GPT")
st.write("This app simulates a customer service interaction using data stored in Snowflake and GPT for generating technical solutions.")

# Step 1: Input phone number
phone_number = st.text_input("Enter customer's phone number", "")

if phone_number:
    # Step 2: Fetch and display customer data
    customer_data = run_query(f"""
        SELECT 
            c.CustomerID, c.CustomerName, c.Email, c.Address,
            s.SaleID, s.ProductCode, s.PurchaseDate, s.Quantity,
            p.ProductName, p.Description, p.ManualLink
        FROM DEMO.ASPA.Contact con
        JOIN DEMO.ASPA.Customer c ON con.CustomerID = c.CustomerID
        JOIN DEMO.ASPA.SalesHistory s ON c.CustomerID = s.CustomerID
        JOIN DEMO.ASPA.Product p ON s.ProductCode = p.ProductCode
        WHERE con.PhoneNumber = '{phone_number}'
    """)
    
    if not customer_data.empty:
        # Convert all column names to lowercase for consistency
        customer_data.columns = customer_data.columns.str.lower()
        
        # Convert date columns to strings for JSON serialization
        customer_data['purchasedate'] = customer_data['purchasedate'].apply(convert_to_serializable)
        
        # Display customer information
        st.subheader("Customer Information")
        customer_info = customer_data[['customername', 'email', 'address']].drop_duplicates().iloc[0]
        st.write(f"**Name:** {customer_info['customername']}")
        st.write(f"**Email:** {customer_info['email']}")
        st.write(f"**Address:** {customer_info['address']}")
        
        # Display purchased products
        st.subheader("Purchased Products")
        purchased_products = customer_data[['productcode', 'productname', 'purchasedate', 'manuallink']]
        st.dataframe(purchased_products)

        # Allow the user to select the product related to the issue
        selected_product = st.selectbox("Select the product related to the issue", purchased_products['productname'])
        product_code = purchased_products[purchased_products['productname'] == selected_product]['productcode'].iloc[0]

        # Toggle Issue History button
        if 'show_issue_history' not in st.session_state:
            st.session_state.show_issue_history = False

        if st.button("Show Issue/Service History"):
            st.session_state.show_issue_history = not st.session_state.show_issue_history
        
        if st.session_state.show_issue_history:
            customer_id = customer_data['customerid'].iloc[0]
            # Fetch issue history for the selected product only
            issue_history = fetch_issue_history(customer_id, product_code)
            if not issue_history.empty:
                st.subheader(f"Issue/Service History for {selected_product}")
                st.dataframe(issue_history)
            else:
                st.write(f"No previous issues found for the selected product: {selected_product}.")
        
        # Step 3: Input issue description
        issue_description = st.text_area("Enter the customer's issue description")

        if issue_description:
            # Step 4: Fetch the manual and show relevant section as bullet points
            manual_text = fetch_manual(product_code)
            if manual_text:
                st.subheader("Manual Section")
                
                # Display the header without bullet points
                st.write(f"**Troubleshooting Steps for '{issue_description}' issue:**")
                
                # Call the function to handle bullet point list and normal text separately
                manual_section = show_manual_section(issue_description, manual_text)
                
                # Display the bullet-point list
                st.markdown(manual_section)
            else:
                st.write("Manual not found for this product.")
            
            # Step 5: Suggest additional products or upgrades
            # st.subheader("Sales Opportunities")
            # st.write("Based on the customer's purchase history, here are some upgrade suggestions or additional products they might be interested in:")
            # for product in purchased_products['productname']:
            #     st.write(f"**{product}**: Consider upgrading to the latest model with enhanced features.")
    else:
        st.write("No customer data found for this phone number.")
