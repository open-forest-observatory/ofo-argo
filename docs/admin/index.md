# Administrator Guides

This section contains guides for administrators who need to set up and configure the OFO Argo
cluster infrastructure.  For day-to-day cluster usage instructions, including cluster resizing and
workflow submission, see the [Cluster usage](../usage) section.

## Guides

<div class="grid cards" markdown>
{% for page in navigation.admin.children %}
{% if page.title != "Administrator Guides" %}
-   **[{{ page.title }}]({{ page.url | url }})**
{% endif %}
{% endfor %}
</div>
