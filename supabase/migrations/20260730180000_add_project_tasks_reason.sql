-- Fix: synchronize project_tasks schema with backend V2 task review model
-- Adds missing column expected by ProjectTemplateReview API

ALTER TABLE siteops_v2.project_tasks
ADD COLUMN IF NOT EXISTS reason TEXT;
