"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-26

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("region_hint", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_scraped_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("platform", "source_type", "value"),
    )

    # ------------------------------------------------------------------
    # posts
    # ------------------------------------------------------------------
    op.create_table(
        "posts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_platform", sa.Text(), nullable=False),
        sa.Column("source_post_id", sa.Text(), nullable=False),
        sa.Column("author_handle", sa.Text(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "scraped_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("engagement", postgresql.JSONB(), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("source_platform", "source_post_id"),
    )
    op.create_index("idx_posts_posted_at", "posts", ["posted_at"])

    # ------------------------------------------------------------------
    # classifications
    # ------------------------------------------------------------------
    op.create_table(
        "classifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "post_id",
            sa.BigInteger(),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("sentiment", sa.Text(), nullable=False),
        sa.Column("referenced_agency", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column(
            "classified_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("post_id"),
    )
    op.create_index("idx_classifications_category", "classifications", ["category"])
    op.create_index("idx_classifications_region", "classifications", ["region"])

    # ------------------------------------------------------------------
    # daily_stats
    # region is part of the PK and therefore NOT NULL.
    # Use '' (empty string) to represent an all-regions aggregate row.
    # ------------------------------------------------------------------
    op.create_table(
        "daily_stats",
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("post_count", sa.Integer(), nullable=False),
        sa.Column("avg_sentiment_score", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("stat_date", "category", "region"),
    )


def downgrade() -> None:
    op.drop_table("daily_stats")
    op.drop_index("idx_classifications_region", table_name="classifications")
    op.drop_index("idx_classifications_category", table_name="classifications")
    op.drop_table("classifications")
    op.drop_index("idx_posts_posted_at", table_name="posts")
    op.drop_table("posts")
    op.drop_table("sources")
