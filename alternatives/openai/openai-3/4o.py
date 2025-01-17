import subprocess
import json
import os
import PyPDF2
from rdflib import Graph, Literal, RDF, URIRef
from urllib.parse import quote  # Import quote for URL encoding
from datetime import datetime  # Import datetime for date formatting
import requests  # Import requests for making API calls
import google.generativeai as genai

# Step 1: Extract text from PDF
def read_pdf(file_path):
    with open(file_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        text = ''
        for page in reader.pages:
            text += page.extract_text() + '\n'
    return text

# Step 2: Preprocess the extracted text
def preprocess_text(text):
    return text.strip()

# Step 3: Define a prompt for the LLM
def create_prompt(text):
    # Wrap the input text in triple quotes
    wrapped_text = f'"""\n{text}\n"""'
    
    return (
        "Extract the following information from the text:\n"
        "1. Case ID\n"
        "2. Language of the case\n"
        "3. Referring court\n"
        "4. Date\n"
        "5. Keywords\n\n"
        f"Text:\n{text}\n\n"
        "Please provide the information in the following JSON format:\n"
        "{\n"
        "  'case_id': '...',\n"
        "  'language': '...',\n"
        "  'referring_court': '...',\n"
        "  'date': '...',\n"
        "  'keywords': [...] \n"
        "}"
    )

# Step 4: Call the OpenAI API
def extract_information_with_openai(text):
    prompt = create_prompt(text)
    headers = {
        'Authorization': 'Bearer ',
        'Content-Type': 'application/json',
    }
    data = {
        'model': 'gpt-4',
        'messages': [
            {'role': 'system', 'content': 'You are a legal document analyzer. Extract information and return it in valid JSON format only.'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.1  # Lower temperature for more consistent outputs
    }
    
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            output = result['choices'][0]['message']['content']
            print("OpenAI Output:", output)  # Debugging line
            return output.strip()
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return ""
            
    except Exception as e:
        print(f"OpenAI API Error: {str(e)}")
        return ""

# Step 5: Post-process the LLM output
def parse_llm_output(output):
    print("Parsing LLM Output:", output)  # Debugging line
    
    if not output.strip():
        print("Error: LLM output is empty.")
        return {}

    # Clean up the output by removing markdown and hashtags
    cleaned_output = output.replace('```json', '').replace('```', '').replace('###', '').strip()
    
    try:
        # Parse the JSON array and take the first object
        json_array = json.loads(cleaned_output)
        if isinstance(json_array, list) and len(json_array) > 0:
            output_dict = json_array[0]
        else:
            output_dict = json_array
            
        # Standardize the date format if present
        if 'date' in output_dict:
            date_str = output_dict['date']
            
            if isinstance(date_str, list):
                date_str = date_str[0]

            try:
                standardized_date = datetime.strptime(date_str, "%d %B %Y").date()
                output_dict['date'] = standardized_date.isoformat()
            except ValueError:
                try:
                    standardized_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                    output_dict['date'] = standardized_date.isoformat()
                except ValueError:
                    print(f"Date format error for: {date_str}")
                    output_dict['date'] = date_str

        return output_dict
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e} for output: {cleaned_output}")
        return {}

# Step 6: Save the extracted information
def save_to_json(data, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# Step 7: Convert JSON to RDF
def json_to_rdf(data, g):
    # Generate a fallback case_id if missing
    if not data.get('case_id'):
        print("Warning: Using fallback identifier")
        fallback_id = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        data['case_id'] = fallback_id

    case_id_encoded = quote(data['case_id'])
    case_uri = URIRef(f"http://example.org/case/{case_id_encoded}")

    # Add all available information to RDF
    g.add((case_uri, RDF.type, URIRef("http://example.org/Case")))
    
    # Map all available fields
    field_mappings = {
        'case_id': 'case_id',
        'language': 'language',
        'referring_court': 'referring_court',
        'date': 'date',
        'type_of_case': 'type_of_case',
        'legal_grounds': 'legal_grounds',
        'rulings': 'rulings'
    }
    
    for field, predicate in field_mappings.items():
        if field in data and data[field]:
            g.add((case_uri, URIRef(f"http://example.org/{predicate}"), Literal(data[field])))
    
    # Handle arrays
    if 'keywords' in data and data['keywords']:
        keywords_literal = Literal(", ".join(data['keywords']))
        g.add((case_uri, URIRef("http://example.org/keyword"), keywords_literal))
        
    if 'parties' in data and data['parties']:
        for index, party in enumerate(data['parties'], start=1):
            party_uri = URIRef(f"http://example.org/party{index}")
            g.add((case_uri, party_uri, Literal(party)))

# Process all PDFs in a folder
def process_folder(folder_path):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, "output.json")
    rdf_file = os.path.join(script_dir, "output.ttl")

    g = Graph()

    for filename in os.listdir(folder_path):
        if filename.endswith('.pdf'):
            file_path = os.path.join(folder_path, filename)
            print(f"Processing file: {file_path}")
            text = read_pdf(file_path)
            cleaned_text = preprocess_text(text)
            llm_output = extract_information_with_openai(cleaned_text)  # Updated to use OpenAI
            extracted_info = parse_llm_output(llm_output)
            
            # Attempt to convert to RDF regardless of 'case_id'
            json_to_rdf(extracted_info, g)
            if 'case_id' not in extracted_info:
                print("Warning: Extracted information is missing 'case_id'. RDF conversion attempted anyway.")

    g.serialize(destination=rdf_file, format='turtle')
    print(f"RDF information saved to: {rdf_file}")
    
    return  # Stop further processing after saving the file

# Usage
if __name__ == "__main__":
    input_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    process_folder(input_folder)