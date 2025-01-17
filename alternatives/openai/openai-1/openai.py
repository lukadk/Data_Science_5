import subprocess
import json
import os
import PyPDF2
from rdflib import Graph, Literal, RDF, URIRef
from urllib.parse import quote  # Import quote for URL encoding
from datetime import datetime  # Import datetime for date formatting
import requests  # Import requests for making API calls

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
        'model': 'gpt-3.5-turbo',  # Specify the model you want to use
        'messages': [{'role': 'user', 'content': prompt}],
    }
    
    response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
    
    if response.status_code == 200:
        result = response.json()
        output = result['choices'][0]['message']['content']
        print("OpenAI Output:", output)  # Debugging line to check OpenAI output
        return output.strip()
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return ""  # Return an empty string or handle as needed

# Step 5: Post-process the LLM output
def parse_llm_output(output):
    print("Parsing LLM Output:", output)  # Debugging line to check output
    
    # Check if output is empty
    if not output.strip():
        print("Error: LLM output is empty.")
        return {}  # Return an empty dictionary or handle as needed

    output = output.replace("'", '"')
    
    # Attempt to load JSON
    try:
        output_dict = json.loads(output)
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e} for output: {output}")
        return {}  # Return an empty dictionary or handle as needed

    # Standardize the date format
    date_str = output_dict['date']
    
    # Check if date_str is a list
    if isinstance(date_str, list):
        # If it's a list, take the first date or handle as needed
        date_str = date_str[0]  # You can change this logic as needed

    # Attempt to parse the date string
    try:
        # Adjust the parsing logic based on expected formats
        if "Official Journal of the European Union publication date" in date_str:
            date_str = date_str.split('(')[0].strip()  # Take only the date part
        standardized_date = datetime.strptime(date_str, "%d %B %Y").date()  # Change format as needed
        output_dict['date'] = standardized_date.isoformat()  # Convert to YYYY-MM-DD format
    except ValueError:
        # Handle different date formats
        try:
            standardized_date = datetime.strptime(date_str, "%d.%m.%Y").date()  # Handle DD.MM.YYYY format
            output_dict['date'] = standardized_date.isoformat()
        except ValueError:
            print(f"Date format error for: {date_str}")
            output_dict['date'] = date_str  # Fallback to original if parsing fails

    return output_dict

# Step 6: Save the extracted information
def save_to_json(data, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# Step 7: Convert JSON to RDF
def json_to_rdf(data, g):
    # Check if 'case_id' exists in the data
    if 'case_id' not in data:
        print("Warning: 'case_id' is missing from the extracted information. RDF conversion skipped.")
        return  # Skip RDF conversion if 'case_id' is not present

    case_id_encoded = quote(data['case_id'])
    case_uri = URIRef(f"http://example.org/case/{case_id_encoded}")

    g.add((case_uri, RDF.type, URIRef("http://example.org/Case")))
    g.add((case_uri, URIRef("http://example.org/case_id"), Literal(data['case_id'])))
    g.add((case_uri, URIRef("http://example.org/language"), Literal(data['language'])))
    g.add((case_uri, URIRef("http://example.org/referring_court"), Literal(data['referring_court'])))
    g.add((case_uri, URIRef("http://example.org/date"), Literal(data['date'])))
    
    # Handle keywords as a single predicate with multiple values
    keywords_literal = Literal(", ".join(data['keywords']))  # Join keywords with a comma
    g.add((case_uri, URIRef("http://example.org/keyword"), keywords_literal))

# Process all PDFs in a folder
def process_folder(folder_path):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, "output.json")  # Save in the same directory
    rdf_file = os.path.join(script_dir, "output.ttl")  # RDF output file

    g = Graph()  # Create a new RDF graph

    for filename in os.listdir(folder_path):
        if filename.endswith('.pdf'):
            file_path = os.path.join(folder_path, filename)
            print(f"Processing file: {file_path}")
            text = read_pdf(file_path)
            cleaned_text = preprocess_text(text)
            llm_output = extract_information_with_openai(cleaned_text)  # Updated function call
            extracted_info = parse_llm_output(llm_output)
            
            # Attempt to convert to RDF regardless of 'case_id'
            json_to_rdf(extracted_info, g)  # Convert JSON to RDF and add to the graph
            if 'case_id' not in extracted_info:
                print("Warning: Extracted information is missing 'case_id'. RDF conversion attempted anyway.")

    g.serialize(destination=rdf_file, format='turtle')  # Save the complete RDF graph

    print(f"RDF information saved to: {rdf_file}")
    
    return  # Stop further processing after saving the file

# Usage
if __name__ == "__main__":
    input_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    process_folder(input_folder)