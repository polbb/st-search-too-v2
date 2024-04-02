import datetime
import boto3
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
import re
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
import os
import json

# Streamlit UI
st.set_page_config(layout="wide")  # Force wide mode
with open("style.css") as css:
    st.markdown(f'<style>{css.read()}</style>', unsafe_allow_html=True)

# AWS Credentials
aws_access_key_id = st.secrets.AWS_ACCESS_KEY_ID
aws_secret_access_key = st.secrets.AWS_SECRET_ACCESS_KEY
aws_default_region = st.secrets.AWS_DEFAULT_REGION

# AWS Services Clients
dynamodb = boto3.resource('dynamodb', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key, region_name=aws_default_region)
s3 = boto3.client('s3', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key, region_name=aws_default_region)

st.title("ArgoXai")
col1, col2, _, _, _, _, _, _ = st.columns([3,3,1,1,1,1,1,1])
fuzzy_search = col1.text_input("Search Documents")
data = st.button("Search")
st.divider()

if data:
    st.write("Starting to scan company_xhtml_data table for company IDs...")
    xhtml_table = dynamodb.Table('company_xhtml_data')
    company_ids = []
    response = xhtml_table.scan()

    company_ids.extend(item['companyID'] for item in response['Items'])

    while 'LastEvaluatedKey' in response:
        response = xhtml_table.scan(
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        company_ids.extend(item['companyID'] for item in response['Items'])

    st.write(f'Number of companies found: {len(set(company_ids))}')

    progress_bar = st.progress(0)
    total_companies = len(set(company_ids))  # Adjusted to reflect unique company IDs

    for index, company_id in enumerate(set(company_ids)):  # Ensure unique company IDs
        st.write(f'Processing company {index + 1} of {total_companies}: {company_id}')
        response = xhtml_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('companyID').eq(company_id),
            ScanIndexForward=False,  # This will ensure the results are returned in descending order
            Limit=1  # We only need the latest item
        )
        st.write('Response retrieved for the latest year.')
        if 'Items' in response and response['Items']:
            latest_item = response['Items'][0]  # Get the first item which is the latest due to ScanIndexForward=False
            s3_key = latest_item['s3key']
            s3_object = s3.get_object(Bucket='company-house', Key=s3_key)
            s3_content = s3_object['Body'].read().decode('utf-8')
            soup = BeautifulSoup(s3_content, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            st.write('Text extracted from XHTML content.')
            
            # Improved extraction and exclusion of the accounting policies section from the search
            accounting_policies_pattern = re.compile(r'(\d+\.?)\s*Accounting Policies.*?(?=\d+\.)', re.IGNORECASE | re.DOTALL)
            accounting_policies_section = accounting_policies_pattern.search(text)
            if accounting_policies_section:
                continuation_pattern = re.compile(r'Accounting Policies.*?(?=\d+\.)', re.IGNORECASE | re.DOTALL)
                continuation_match = continuation_pattern.search(text, accounting_policies_section.end())
                if continuation_match:
                    text = text[:accounting_policies_section.start()] + text[continuation_match.end():]
                else:
                    text = text[:accounting_policies_section.start()]
            
            sentences = re.split(r'(?<=[.!?]) +', text)
            company_matches = []
            
            for sentence in sentences:
                if fuzz.partial_ratio(fuzzy_search.lower(), sentence.lower()) >= 100:
                    sentence_index = sentences.index(sentence)
                    context = ' '.join(sentences[max(0, sentence_index-1):min(len(sentences), sentence_index+2)])
                    company_matches.append({'CompanyID': company_id, 'Matching Sentence': context})
            
            if company_matches:
                st.markdown(f"### Matching Results for Company Number: {company_id}")
                for match in company_matches:
                    st.markdown(f"**Matching Sentence:** {match['Matching Sentence']}")
                    st.markdown("---")
            else:
                st.write(f"No matching sentences found for company {company_id}.")
                    
        progress_bar.progress((index + 1) / total_companies)

