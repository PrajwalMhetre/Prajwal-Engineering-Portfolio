"""Initial portfolio API schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_portfolio_api"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("contact_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("ip_hash", sa.CHAR(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_contact_messages_email", "contact_messages", ["email"])
    op.create_index("ix_contact_messages_status", "contact_messages", ["status"])
    op.create_index("ix_contact_messages_ip_created", "contact_messages", ["ip_hash", "created_at"])
    op.create_table("portfolio_projects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tech_stack", sa.Text(), nullable=False, server_default=""),
        sa.Column("repository_url", sa.String(500)),
        sa.Column("demo_url", sa.String(500)),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_portfolio_projects_slug", "portfolio_projects", ["slug"])
    op.create_index("ix_portfolio_projects_category", "portfolio_projects", ["category"])
    op.create_table("project_views",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("project_slug", sa.String(100), nullable=False),
        sa.Column("referrer", sa.String(500)),
        sa.Column("ip_hash", sa.CHAR(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_project_views_project_slug", "project_views", ["project_slug"])
    op.create_index("ix_project_views_created_at", "project_views", ["created_at"])
    for table in ("contact_messages", "portfolio_projects", "project_views"):
        op.execute(sa.text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated'))
    for sequence in ("contact_messages_id_seq", "portfolio_projects_id_seq", "project_views_id_seq"):
        op.execute(sa.text(f'REVOKE ALL ON SEQUENCE public."{sequence}" FROM anon, authenticated'))

def downgrade():
    for table in ("project_views", "portfolio_projects", "contact_messages"):
        op.drop_table(table)
