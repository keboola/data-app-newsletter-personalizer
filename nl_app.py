import streamlit as st
from openai import OpenAI
from kbcstorage.client import Client
import os
from bs4 import BeautifulSoup, NavigableString
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

# Load the OpenAI API key and Keboola credentials from secrets
token = st.secrets["storage_token"]
kbc_url = st.secrets["url"]
api_key = st.secrets["api_key"]

client_kbl = Client(kbc_url, token)
client = OpenAI(api_key=api_key)


# Change the color of buttons in the Streamlit app
def change_button_color(font_color: str, background_color: str, border_color: str):
    button_style = f"""
    <style>
        .stButton > button {{
            color: {font_color};
            background-color: {background_color};
            border: 1px solid {border_color};
        }}
    </style>
    """
    st.markdown(button_style, unsafe_allow_html=True)


LOGO_IMAGE_PATH = os.path.abspath("./static/keboola.png")
st.set_page_config(page_title="Newsletter Data app", layout="wide")


# Hide anchor links in markdown headers
def hide_custom_anchor_links():
    st.markdown(
        """
        <style>
        h1 > a, h2 > a, h3 > a, h4 > a, h5 > a, h6 > a {
            display: none !important;
        }
        [data-testid="stMarkdown"] h1 a, [data-testid="stMarkdown"] h2 a, [data-testid="stMarkdown"] h3 a, 
        [data-testid="stMarkdown"] h4 a, [data-testid="stMarkdown"] h5 a, [data-testid="stMarkdown"] h6 a {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# Display footer with copyright and version information
def display_footer():
    st.markdown(
        """
        <style>
        .footer {
            width: 100%;
            font-size: 14px; 
            color: #22252999; 
            padding: 10px 0;  
            display: flex; 
            justify-content: space-between;
            align-items: center.
        }
        .footer p {
            margin: 0;  
            padding: 0;  
        }
        </style>
        <div class="footer">
            <p>(c) Keboola 2024</p>
            <p>Version 2.0</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.image(LOGO_IMAGE_PATH)
hide_img_fs = """
    <style>
    button[title="View fullscreen"]{
        visibility: hidden;
    }
    </style>
"""
st.markdown(hide_img_fs, unsafe_allow_html=True)
st.title("Data app for personalized newsletters")

st.sidebar.header("")
change_button_color("#FFFFFF", "#1EC71E", "#1EC71E")

uploaded_file = st.sidebar.file_uploader("**Upload Newsletter (HTML):**", type=["html"])

if "customer_segments" not in st.session_state:
    st.session_state.customer_segments = [""]

if "keboola_links" not in st.session_state:
    st.session_state.keboola_links = []

if "html_content" not in st.session_state:
    st.session_state.html_content = ""

if "personalized_html" not in st.session_state:
    st.session_state.personalized_html = {}


# Add a new customer segment to the session state
def add_customer_segment():
    st.session_state.customer_segments.append("")


st.sidebar.markdown("**Insert customer segments:**")
for i, segment in enumerate(st.session_state.customer_segments):
    st.session_state.customer_segments[i] = st.sidebar.text_input(
        f"Segment {i + 1}", value=segment, key=f"segment_{i}"
    )

if len(st.session_state.customer_segments) > 0:
    st.sidebar.button("Add Another Segment", on_click=add_customer_segment)


# Save the personalized HTML content to Keboola
def save_to_keboola(html_content: str, segment_name: str):
    file_name = f"personalized_newsletter_{segment_name}.html"
    with open(file_name, "w") as file:
        file.write(html_content)
    file_path = os.path.abspath(file_name)
    response = client_kbl.files.upload_file(file_path)
    os.remove(file_path)

    if isinstance(response, int):
        file_id = response
        file_details = client_kbl.files.detail(file_id)
        if isinstance(file_details, dict) and "url" in file_details:
            download_url = file_details["url"]
            st.session_state.keboola_links.append((segment_name, download_url))
            st.success(
                f"Newsletter for {segment_name} saved to Keboola! [Download it here]({download_url})"
            )
        else:
            st.error("File details response does not contain 'url'.")
    else:
        st.error("Response from Keboola API is not an integer.")


# Validate the personalized text against the original HTML content
def is_text_valid(original_html: str, personalized_html: str) -> bool:
    original_soup = BeautifulSoup(original_html, "html.parser")
    personalized_soup = BeautifulSoup(personalized_html, "html.parser")

    original_text = original_soup.get_text(separator=" ", strip=False).strip()
    personalized_text = personalized_soup.get_text(separator=" ", strip=False).strip()

    length_threshold = 1 * len(original_text)
    if abs(len(original_text) - len(personalized_text)) > length_threshold:
        logging.warning(
            f"Length mismatch: original ({len(original_text)}) vs personalized ({len(personalized_text)})"
        )
        return False

    tags = [
        "<a",
        "</a>",
        "<b",
        "</b>",
        "<i",
        "</i>",
        "<button>",
        "</button>",
        "<img>",
        "<video>",
    ]
    for tag in tags:
        if (tag in original_html) and (tag not in personalized_html):
            logging.warning(f"Missing HTML tag {tag} in personalized text")
            return False

    return True


# Generate personalized text using OpenAI API
def generate_personalized_text(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt}],
        max_tokens=1024,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


# Personalize the HTML content for a specific customer segment
def personalize_html(html_content: str, segment_name: str) -> str:
    logging.info(f"Personalizing HTML for segment: {segment_name}")
    soup = BeautifulSoup(html_content, "html.parser")
    tags = soup.find_all(["p", "b", "i", "span"])

    max_attempts = 3

    for tag in tags:
        # Skip <a>, <button>, <img>, and <video> tags
        if tag.name in ["a", "button", "img", "video"]:
            continue

        original_html = tag.decode_contents()
        original_text = tag.get_text(separator=" ", strip=False).strip()

        if "unsubscribe" in original_text.lower():
            continue

        if original_text:
            prompt = f"""
            You are a senior specialist for newsletters. 
            You are tasked with personalizing the words and sentences of the newsletter for a specific segment of customers.
            If its word, keep one word, if its sentence, keep the sentence.

            Important guidelines to follow:
            ! Keep the length of the text approximately the same as the original.
            ! Preserve the original language.
            ! Do not use the name of the segment in the text.
            ! If the text is too short, you can leave it original - do not comment on this.

            Remember:
            - Process it by sentences, only change the content of specific sentences !!!
            - Keep the length !!!
            - If in the text is a URL, do not change it.
            - If in the text are formatting and white spaces, do not change it.
            - Do not change the text in buttons.

            Adjust the following text to be personalized for the given segment:

            Segment: {segment_name}

            Change just this part of text: {original_text}

            ! Preserve the original language.
            """

            attempt = 0
            while attempt < max_attempts:
                logging.info(f"Attempt {attempt + 1} for segment {segment_name}")
                personalized_text = generate_personalized_text(prompt)
                logging.info(
                    f"Original: {original_text}, Personalized: {personalized_text}"
                )

                personalized_tag = BeautifulSoup(personalized_text, "html.parser")

                if is_text_valid(original_html, str(personalized_tag)):
                    tag.clear()
                    tag.append(BeautifulSoup(personalized_text, "html.parser"))
                    logging.info(
                        f"Personalization successful for segment {segment_name} on attempt {attempt + 1}"
                    )
                    break
                else:
                    attempt += 1
                    logging.warning(
                        f"Invalid personalization for segment {segment_name}, attempt {attempt}. Retrying..."
                    )

            if attempt == max_attempts:
                logging.error(
                    f"Failed to personalize text for segment {segment_name} after {max_attempts} attempts. Reverting to original text."
                )
                tag.clear()
                tag.append(BeautifulSoup(original_html, "html.parser"))
        elif tag.string is not None:
            tag.string.replace_with(NavigableString(""))

    return str(soup)


# Display the original and personalized newsletters side by side
def display_newsletters(personalized_html: str, original_html: str):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Personalized Newsletter")
        st.components.v1.html(personalized_html, height=800, scrolling=True)

    with col2:
        st.markdown("### Original Newsletter")
        st.components.v1.html(original_html, height=800, scrolling=True)


# Handle the personalization workflow for a segment
def handle_personalization_workflow(html_content: str, segment: str):
    logging.info(f"Handling personalization workflow for segment: {segment}")

    if segment not in st.session_state.personalized_html:
        st.session_state.personalized_html[segment] = personalize_html(
            html_content, segment
        )

    st.text("")

    if "selected_segment" in st.session_state:
        selected_segment = st.session_state.selected_segment

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Allow"):
                save_to_keboola(
                    st.session_state.personalized_html[selected_segment],
                    selected_segment,
                )

            if st.button("Re-personalize", key=f"re_personalize_{segment}"):
                st.session_state.personalized_html[segment] = personalize_html(
                    html_content, segment
                )


# Button to generate personalized newsletters
if st.sidebar.button("Generate Personalized Newsletters"):
    if uploaded_file is not None:
        html_content = uploaded_file.read().decode("utf-8")
        st.session_state.html_content = html_content
        st.session_state.personalized_html = {}  # Reset personalized HTML

        progress_bar = st.progress(0)
        total_segments = len(st.session_state.customer_segments)

        processing_text = st.empty()

        for idx, segment in enumerate(st.session_state.customer_segments):
            if segment:
                processing_text.text(f"Processing segment {idx + 1}/{total_segments}")
                handle_personalization_workflow(html_content, segment)
                progress_bar.progress((idx + 1) / total_segments)

        progress_bar.empty()
        processing_text.empty()

        if st.session_state.keboola_links:
            st.markdown("### Download personalized newsletters:")
            for segment, link in st.session_state.keboola_links:
                st.markdown(f"[Download {segment} newsletter]({link})")

        # Display the selectbox after generating newsletters
        if (
            "personalized_html" in st.session_state
            and st.session_state.personalized_html
        ):
            selected_segment = st.selectbox(
                "Choose a segment to display:", st.session_state.customer_segments
            )

            if selected_segment in st.session_state.personalized_html:
                display_newsletters(
                    st.session_state.personalized_html[selected_segment],
                    st.session_state.html_content,
                )

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Allow"):
                        save_to_keboola(
                            st.session_state.personalized_html[selected_segment],
                            selected_segment,
                        )

                    if st.button(
                        "Re-personalize", key=f"re_personalize_{selected_segment}"
                    ):
                        st.session_state.personalized_html[
                            selected_segment
                        ] = personalize_html(
                            st.session_state.html_content, selected_segment
                        )
    else:
        st.info("Please upload a newsletter first.")
else:
    # Ensure selectbox is not shown initially
    if "personalized_html" in st.session_state and st.session_state.personalized_html:
        selected_segment = st.selectbox(
            "Choose a segment to display:", st.session_state.customer_segments
        )

        if selected_segment in st.session_state.personalized_html:
            display_newsletters(
                st.session_state.personalized_html[selected_segment],
                st.session_state.html_content,
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button("Allow"):
                    save_to_keboola(
                        st.session_state.personalized_html[selected_segment],
                        selected_segment,
                    )

                if st.button(
                    "Re-personalize", key=f"re_personalize_{selected_segment}"
                ):
                    st.session_state.personalized_html[
                        selected_segment
                    ] = personalize_html(
                        st.session_state.html_content, selected_segment
                    )

display_footer()
