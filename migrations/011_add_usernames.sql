BEGIN;

-- Add the new username column
ALTER TABLE public.users
ADD COLUMN username VARCHAR(32);

-- Generate unique usernames for existing accounts
UPDATE public.users
SET username = 'user_' || REPLACE(id::text, '-', 'n');

-- Require a username for every account
ALTER TABLE public.users
ALTER COLUMN username SET NOT NULL;

-- Require lowercase usernames
ALTER TABLE public.users
ADD CONSTRAINT ck_users_username_lowercase
CHECK (username = LOWER(username));

-- Prevent duplicate usernames
CREATE UNIQUE INDEX ix_users_username
ON public.users (username);

COMMIT;
