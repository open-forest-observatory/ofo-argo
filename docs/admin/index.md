# Administrator Guides

This section contains guides for administrators who need to set up and configure the OFO Argo
cluster infrastructure.  For day-to-day cluster usage instructions, including cluster resizing and
workflow submission, see the [Cluster usage](../usage) section.

## Guides

<div class="grid cards" markdown>
{% for item in navigation %}
{% if item.title == "Administrator Guides" and item.children %}
{% for page in item.children | sort(attribute='meta.nav_order') %}
{% if page.is_page %}
-   **[{{ page.title }}]({{ page.url }})**
{% endif %}
{% endfor %}
{% endif %}
{% endfor %}
</div>
