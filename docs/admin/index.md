# Administrator Guides

This section contains guides for administrators who need to set up and configure the OFO Argo
cluster infrastructure.  For day-to-day cluster usage instructions, including cluster resizing and
workflow submission, see the [Cluster usage](../usage) section.

## Guides

{% for item in navigation %}
{% if item.title == "Administrator Guides" and item.children %}
{% for page in item.children %}
{% if page.is_page %}

**DEBUG PAGE OBJECT:**
- page object: `{{ page }}`
- page.title: `{{ page.title }}`
- page.file: `{{ page.file }}`
- page.file.name: `{{ page.file.name }}`
- Has page.file.page?: `{{ 'yes' if page.file.page else 'no' }}`
{% if page.file.page %}
- page.file.page.title: `{{ page.file.page.title }}`
- page.file.page.meta: `{{ page.file.page.meta }}`
{% endif %}

{% endif %}
{% endfor %}
{% endif %}
{% endfor %}
