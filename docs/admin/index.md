# Administrator Guides

This section contains guides for administrators who need to set up and configure the OFO Argo
cluster infrastructure.  For day-to-day cluster usage instructions, including cluster resizing and
workflow submission, see the [Cluster usage](../usage) section.

## Guides

<div class="grid cards" markdown>
{% for item in navigation %}
{% if item.title == "Administrator Guides" and item.children %}
{% set sorted_pages = item.children | selectattr('is_page') | list %}
{% for page in sorted_pages %}
-   **[{{ page.file.page.title }}]({{ page.url }})**
{% endfor %}
{% endif %}
{% endfor %}
</div>
