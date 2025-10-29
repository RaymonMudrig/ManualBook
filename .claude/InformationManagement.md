Information management
======================

# Nature of query
- What
- How

# Scope of knowledge
## 1. Infrastructure of application.
Various aspect of application are:
	- Menu
	- Config
	- Workspace
	- Widget
	- Template of workspace
	- User's watchlist of data
	
## 2. Information / document unit to display or work on.
Various aspect of informations are:
	- Data type.
	- Data presentation: numbers, table, chart.
	- Widget code or name displaying what datas.

# Information strategy
The goals is to provide high quality of information, which means:
- Accurate, no hallucination.
- Complete, detailed explanation along with images and illustration.
- Enriched with information about its relation to another information.

The challenge is how to structured the document so that the agent can resolved the accurate information to retrieve and displays them comprehensively.

## 1. Plan of data store
One alternatif is to store them in two different form:
1. Cataloged information/article that can be to retrieved as is.
2. Searching index or helper to select the accurate information and articles.

## 2. Prepare the source of data
Then how we structured the source document (*.md) so that it is ready to use to generate those 2 category data store. Using only markdown formatting facilities such as headings list table code-fence etc is insufficient, since their purpose is for structure and presentation.
We need some kind of meta-data to tag each of article for AI can identify information such as: nature of information (what or how), what subject/topic/data type, and relations with other information.

## 3. Parse data into store
If we plan well, parsing data, identify and store them should be easy.
- parse data using heading based as a grouping mechanism to create articles.
- identify the article by its meta-data and create info such as 
    {
        "nature": "what",
        "category": "data", or "app-infra"
        "identifier": "orderbook data",
        "related-identifier": ["widget", "price data", "stock"],
        etc ...
    }
- Use LLM tools to create semantic understanding and store them into vector index.
- Store the complete article along with all images and illustration. List this entry into catalog.

# Retrieving Information semantically
When user ask an information, the agent should identify the nature and which category or identifier (or code or name) it refers to. Then based on this data retrieval performed by combining semantic response attached with well formatted article content.

If the agent cannot find a relevant information in our storage then it will try on internet.
