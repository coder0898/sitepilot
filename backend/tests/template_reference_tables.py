"""Tables a template test database needs since Phase 2 reference material:
template reads, clone, delete and publish all touch the reference links."""
from app.execution_models import FileObject
from app.template_models import V2TemplateGateReferenceFile, V2TemplateTaskReferenceFile

TEMPLATE_REFERENCE_TABLES = (
    FileObject.__table__,
    V2TemplateTaskReferenceFile.__table__,
    V2TemplateGateReferenceFile.__table__,
)
