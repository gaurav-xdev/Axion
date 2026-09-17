"""Add skill definitions, skill executions, and skill metrics tables.

Revision ID: 0002_add_skill_system
Revises: 0001_initial_schema
Create Date: 2026-09-17 12:10:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0002_add_skill_system'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Skill Definitions
    op.create_table(
        'skill_definitions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('skill_id', sa.String(128), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(64), nullable=False, index=True),
        sa.Column('purpose', sa.Text(), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, index=True),
        sa.Column('input_schema', sa.JSON(), nullable=False),
        sa.Column('output_schema', sa.JSON(), nullable=False),
        sa.Column('prerequisites', sa.JSON(), nullable=False),
        sa.Column('required_capabilities', sa.JSON(), nullable=False),
        sa.Column('allowed_tool_names', sa.JSON(), nullable=False),
        sa.Column('procedure', sa.JSON(), nullable=False),
        sa.Column('verification_procedure', sa.JSON(), nullable=False),
        sa.Column('failure_modes', sa.JSON(), nullable=False),
        sa.Column('rollback_strategy', sa.JSON(), nullable=True),
        sa.Column('quality_requirements', sa.JSON(), nullable=False),
        sa.Column('security_constraints', sa.JSON(), nullable=False),
        sa.Column('permission_requirements', sa.JSON(), nullable=False),
        sa.Column('risk_class', sa.String(32), nullable=False),
        sa.Column('estimated_effort', sa.Float(), nullable=False),
        sa.Column('expected_duration_seconds', sa.Integer(), nullable=False),
        sa.Column('cost_estimate', sa.Float(), nullable=False),
        sa.Column('reusable_components', sa.JSON(), nullable=False),
        sa.Column('evidence_requirements', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deprecated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.UniqueConstraint('skill_id', 'version', name='uq_skill_definitions_skill_id_version'),
    )

    # 2. Skill Executions
    op.create_table(
        'skill_executions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('skill_definition_id', sa.String(36), sa.ForeignKey('skill_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('skill_id', sa.String(128), nullable=False, index=True),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('project_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agent_run_id', sa.String(36), sa.ForeignKey('agent_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True, index=True),
        sa.Column('status', sa.String(32), nullable=False, index=True),
        sa.Column('current_step', sa.Integer(), nullable=False),
        sa.Column('max_steps', sa.Integer(), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('max_retries', sa.Integer(), nullable=False),
        sa.Column('input_payload', sa.JSON(), nullable=False),
        sa.Column('output_payload', sa.JSON(), nullable=True),
        sa.Column('checkpoint_json', sa.JSON(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('metrics_json', sa.JSON(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('failure_class', sa.String(32), nullable=True),
        sa.Column('cost', sa.Float(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 3. Skill Metrics
    op.create_table(
        'skill_metrics',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('skill_id', sa.String(128), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('execution_count', sa.Integer(), nullable=False),
        sa.Column('success_count', sa.Integer(), nullable=False),
        sa.Column('failure_count', sa.Integer(), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('verification_failure_count', sa.Integer(), nullable=False),
        sa.Column('total_duration_ms', sa.Integer(), nullable=False),
        sa.Column('total_cost', sa.Float(), nullable=False),
        sa.Column('reuse_count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('skill_id', 'version', name='uq_skill_metrics_skill_id_version'),
    )

def downgrade() -> None:
    op.drop_table('skill_metrics')
    op.drop_table('skill_executions')
    op.drop_table('skill_definitions')
