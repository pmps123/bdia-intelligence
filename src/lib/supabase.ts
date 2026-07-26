import { createClient } from "@supabase/supabase-js";

// Service-role key — server-side only, never sent to the browser. Used exclusively
// by API routes that need to write to Storage on the user's behalf.
export const supabaseAdmin = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export const NOTE_ATTACHMENTS_BUCKET = "note-attachments";
export const UPLOADS_BUCKET = "uploads";
