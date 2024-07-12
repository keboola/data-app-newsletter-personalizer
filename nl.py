import streamlit as st
from openai import OpenAI
from kbcstorage.client import Client
import os
import re
from bs4 import BeautifulSoup
import streamlit.components.v1 as components


# Load the OpenAI API key and Keboola credentials from secrets
token = st.secrets["storage_token"]
kbc_url = st.secrets["url"]

client_kbl = Client(kbc_url, token)
client = OpenAI(api_key=st.secrets["api_key"])


# Function to change button colors
def change_button_color(font_color, background_color, border_color):
    button_html = f"""
    <style>
        .stButton > button {{
            color: {font_color};
            background-color: {background_color};
            border: 1px solid {border_color};
        }}
    </style>
    """
    st.markdown(button_html, unsafe_allow_html=True)


# Function to display logo
LOGO_IMAGE_PATH = os.path.abspath("./app/static/keboola.png")

# Set page title and icon
st.set_page_config(page_title="NL Data app", page_icon=LOGO_IMAGE_PATH, layout="wide")


# Function to hide custom anchor links
def hide_custom_anchor_link():
    st.markdown(
        """
        <style>
        /* Hide anchors directly inside custom HTML headers */
        h1 > a, h2 > a, h3 > a, h4 > a, h5 > a, h6 > a {
            display: none !important;
        }
        /* If the above doesn't work, it may be necessary to target by attribute if Streamlit adds them dynamically */
        [data-testid="stMarkdown"] h1 a, [data-testid="stMarkdown"] h2 a, [data-testid="stMarkdown"] h3 a, 
        [data-testid="stMarkdown"] h4 a, [data-testid="stMarkdown"] h5 a, [data-testid="stMarkdown"] h6 a {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# Function to write data to Keboola - incremental loading
def write_to_keboola(data, table_name, table_path, incremental):
    data.to_csv(table_path, index=False, compression="gzip")
    client_kbl.tables.load(
        table_id=table_name, file_path=table_path, is_incremental=incremental
    )


# Function to display footer
def display_footer_section():
    st.markdown(
        """
    <style>
    .footer {
        width: 100%;
        font-size: 14px; /* Adjust font size as needed */
        color: #22252999; /* Adjust text color as needed */
        padding: 10px 0;  /* Adjust padding as needed */
        display: flex; 
        justify-content: space-between;
        align-items: center;
    }
    .footer p {
        margin: 0;  /* Removes default margin for p elements */
        padding: 0;  /* Ensures no additional padding is applied */
    }
    </style>
    <div class="footer">
        <p>(c) Keboola 2024</p>
        <p>Version 2.0</p>
    </div>
    """,
        unsafe_allow_html=True,
    )


# Display logo and title
st.image(LOGO_IMAGE_PATH)
hide_img_fs = """
        <style>
        button[title="View fullscreen"]{
            visibility: hidden;}
        </style>
        """
st.markdown(hide_img_fs, unsafe_allow_html=True)

st.title("Data app for personalised newsletters")


# Function to count tokens
def count_tokens(text):
    return len(text.split())


# Function to generate personalized newsletter content
@st.cache_data(ttl=7200, show_spinner=False)
def generate_newsletter_content(segment_description, part, platform):
    prompt = f"""
    Please personalize the following HTML newsletter content to fit the specified segment. 
    Ensure that the structure and content are similar in length and style to the original.
    Do not add any new parts or text.
    Do not change addresses, links, or buttons.
    Do not include any comments or explanations in the output, only the personalized HTML content.

    Newsletter HTML Content:
    {part}

    Ensure the tone matches with the segment description {segment_description}.
    """

    if count_tokens(prompt) > 4096:
        st.warning(
            "The combined prompt exceeds the maximum token limit. Please shorten the input."
        )
        return ""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        error_message = str(e)
        if "insufficient_quota" in error_message:
            st.error(
                "You have exceeded your OpenAI API quota. Please check your plan and billing details."
            )
        else:
            st.error(f"An error occurred: {error_message}")
        return ""


# Function to process parts of the HTML content
def process_parts(segment_description, parts, platform):
    personalized_content = ""
    total_parts = len(parts)
    progress_bar = st.progress(0)  # Initialize progress bar
    status_text = st.empty()  # Initialize status text

    for i, part in enumerate(parts):
        content = generate_newsletter_content(segment_description, part, platform)
        if content:
            personalized_content += content
            progress_percentage = (i + 1) / total_parts
            progress_bar.progress(progress_percentage)
            status_text.text(
                f"Completed part {i + 1}/{total_parts}"
            )  # Update status text
        else:
            break
    return personalized_content


# Function to split HTML content into parts
def split_html(soup, max_length):
    html_str = str(soup)
    parts = re.findall(".{1,%d}(?:<[^>]*>|$)" % max_length, html_str)
    return parts


# Function to process the HTML file and generate personalized content
def process_file(segment_description, html_content, platform):
    soup = BeautifulSoup(html_content, "html.parser")
    buttons = soup.find_all("button")
    for button in buttons:
        button.replace_with(f"BUTTON_PLACEHOLDER_{buttons.index(button)}")
    parts = split_html(soup, 6000)
    personalized_content = process_parts(segment_description, parts, platform)
    personalized_soup = BeautifulSoup(personalized_content, "html.parser")
    for button in buttons:
        placeholder = f"BUTTON_PLACEHOLDER_{buttons.index(button)}"
        placeholder_tag = personalized_soup.find(text=placeholder)
        if placeholder_tag:
            placeholder_tag.replace_with(button)
    return str(personalized_soup)


# Function to extract text from HTML content
def extract_text_from_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    text_elements = soup.find_all(string=True)
    text_content = [text.strip() for text in text_elements if text.strip()]
    return text_content


# Function to replace text in HTML content
def replace_text_in_html(html_content, modified_texts):
    soup = BeautifulSoup(html_content, "html.parser")
    for text_element in soup.find_all(string=True):
        stripped_text = text_element.strip()
        if stripped_text in modified_texts:
            text_element.replace_with(modified_texts[stripped_text])
    return str(soup)


# Sidebar for input
st.sidebar.header("")

# Upload newsletter
uploaded_file = st.sidebar.file_uploader("**Upload Newsletter (HTML):**", type=["html"])

# Initialize session state for dynamic customer segments
if "customer_segments" not in st.session_state:
    st.session_state.customer_segments = [""]


# Function to add new customer segment
def add_customer_segment():
    st.session_state.customer_segments.append("")


# Display customer segments input fields
st.sidebar.markdown("**Customer segments:**")
for i, segment in enumerate(st.session_state.customer_segments):
    st.session_state.customer_segments[i] = st.sidebar.text_input(
        f"Segment {i + 1}", value=segment, key=f"segment_{i}"
    )

# Button to add new segment
if len(st.session_state.customer_segments) > 0:
    st.sidebar.button("Add Segment", on_click=add_customer_segment)

# Input for platform (moved below segments)
platform = st.sidebar.text_input(
    "**Used platform for emailing:**",
    help="Recommended specify the platform used for emailing (e.g., Mailchimp, SendGrid).",
)

# Initialize session state for personalized newsletters
if "personalized_newsletters" not in st.session_state:
    st.session_state.personalized_newsletters = {}
if "original_newsletter" not in st.session_state:
    st.session_state.original_newsletter = None
if "keboola_links" not in st.session_state:
    st.session_state.keboola_links = []


# Function to handle saving the file to Keboola
def save_to_keboola(html_content, segment_name):
    file_name = f"personalized_newsletter_{segment_name}.html"
    with open(file_name, "w") as file:
        file.write(html_content)
    file_path = os.path.abspath(file_name)
    response = client_kbl.files.upload_file(file_path)
    os.remove(file_path)  # Clean up the local file after upload

    # Check if the response is an integer (file ID)
    if isinstance(response, int):
        file_id = response
        # Get file details using the file ID
        file_details = client_kbl.files.detail(file_id)

        # Check if file_details is a dictionary and contains the expected keys
        if isinstance(file_details, dict) and "url" in file_details:
            download_url = file_details["url"]
            st.session_state.keboola_links.append((segment_name, download_url))
            st.success(f"Newsletter for {segment_name} saved to Keboola!")
        else:
            st.error("File details response does not contain 'url'.")
    else:
        st.error("Response from Keboola API is not an integer.")


# Function to regenerate the newsletter for the selected segment
def regenerate_newsletter(segment_name, segment_description, platform, newsletter_html):
    st.info(f"Regenerating newsletter for {segment_name}...")

    progress_bar = st.progress(0)  # Initialize progress bar
    status_text = st.empty()  # Initialize status text

    # Split the HTML content into parts
    soup = BeautifulSoup(newsletter_html, "html.parser")
    buttons = soup.find_all("button")
    for button in buttons:
        button.replace_with(f"BUTTON_PLACEHOLDER_{buttons.index(button)}")
    parts = split_html(soup, 6000)

    # Regenerate the personalized content with progress
    total_parts = len(parts)
    personalized_content = ""
    for i, part in enumerate(parts):
        content = generate_newsletter_content(
            segment_description.strip(), part, platform
        )
        if content:
            personalized_content += content
            progress_percentage = (i + 1) / total_parts
            progress_bar.progress(progress_percentage)
            status_text.text(f"Completed part {i + 1}/{total_parts}")
        else:
            st.error("Error in generating content for one of the parts.")
            return

    personalized_soup = BeautifulSoup(personalized_content, "html.parser")
    for button in buttons:
        placeholder = f"BUTTON_PLACEHOLDER_{buttons.index(button)}"
        placeholder_tag = personalized_soup.find(text=placeholder)
        if placeholder_tag:
            placeholder_tag.replace_with(button)

    # Update the session state with the new personalized newsletter
    st.session_state.personalized_newsletters[segment_name] = str(personalized_soup)
    st.success(f"Newsletter for {segment_name} regenerated!")

    # Ensure progress bar reaches 100% at the end
    progress_bar.progress(1.0)
    status_text.text("Regeneration completed!")


# Button to generate newsletters
if st.sidebar.button("Generate Personalized Newsletters"):
    if not uploaded_file:
        st.warning(
            "First of all you need to upload the original newsletter.", icon="⚠️"
        )
    else:
        try:
            newsletter_html = uploaded_file.read().decode("utf-8")
            st.session_state.original_newsletter = newsletter_html  # Save original HTML
            if st.session_state.customer_segments:
                total_segments = len(st.session_state.customer_segments)
                overall_progress_bar = st.progress(0)  # Initialize overall progress bar
                overall_status_text = st.empty()  # Initialize overall status text

                for idx, segment in enumerate(st.session_state.customer_segments):
                    if segment.strip():
                        overall_status_text.text(
                            f"Processing Segment {idx + 1}/{total_segments}..."
                        )  # Update overall status
                        personalized_html = process_file(
                            segment.strip(), newsletter_html, platform
                        )
                        st.session_state.personalized_newsletters[
                            f"Segment {idx + 1}"
                        ] = personalized_html
                        overall_progress_bar.progress(
                            (idx + 1) / total_segments
                        )  # Update overall progress
                        overall_status_text.text(
                            f"Completed Segment {idx + 1}/{total_segments}"
                        )  # Update overall status

                overall_progress_bar.progress(
                    1.0
                )  # Ensure progress bar reaches 100% at the end
                overall_status_text.text(
                    "All segments completed!"
                )  # Final status update
        except Exception as e:
            st.error(f"An error occurred: {e}")


# Function to display generated newsletters
def display_generated_newsletters():
    if (
        st.session_state.original_newsletter
        and st.session_state.personalized_newsletters
    ):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### Original Newsletter")
            components.html(
                st.session_state.original_newsletter,
                width=600,
                height=800,
                scrolling=True,
            )
        with col2:
            st.markdown("### Personalized Newsletter")
            selected_segment = st.selectbox(
                "Select Segment", list(st.session_state.personalized_newsletters.keys())
            )
            st.markdown(
                f"Segment Description: {st.session_state.customer_segments[int(selected_segment.split(' ')[1]) - 1]}"
            )
            components.html(
                st.session_state.personalized_newsletters[selected_segment],
                width=600,
                height=800,
                scrolling=True,
            )
            change_button_color("#FFFFFF", "#1EC71E", "#1EC71E")
            if st.button("Allow", help="Save the newsletter to Keboola."):
                save_to_keboola(
                    st.session_state.personalized_newsletters[selected_segment],
                    selected_segment,
                )
            if st.button("Repeat", help="Regenerate the newsletter for the selected segment."):
                regenerate_newsletter(
                    selected_segment,
                    st.session_state.customer_segments[
                        int(selected_segment.split(" ")[1]) - 1
                    ],
                    platform,
                    st.session_state.original_newsletter,
                )


# Display generated newsletters
display_generated_newsletters()

# Display links to saved newsletters in the sidebar
if st.session_state.keboola_links:
    st.sidebar.markdown("### Done:")
    for segment_name, download_url in st.session_state.keboola_links:
        st.sidebar.markdown(f"[{segment_name}]({download_url})")

# Display footer
display_footer_section()
