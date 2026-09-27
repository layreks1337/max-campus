/** Типы API. Соответствуют схемам бэкенда (backend/app/api/schemas.py).
 *
 * Их можно генерировать автоматически: `npm run api:types` кладёт схему
 * из /api/openapi.json в src/shared/api-schema.d.ts. Здесь — рабочий срез,
 * которым пользуются экраны.
 */

export interface Student {
  id: number;
  full_name: string;
  short_name: string;
  first_name: string;
  group_name: string;
  faculty: string;
  course: number;
  record_book_no: string;
  education_form: string;
  funding: string;
  /** Демо-копия для экспертов (зачётка DEMO-…): синтетический профиль */
  is_demo?: boolean;
}

export interface Staff {
  full_name: string;
  department: string;
  role: string;
  position: string;
}

export interface Me {
  max_user_id: number;
  display_name: string;
  photo_url: string;
  is_bound: boolean;
  role: string;
  student: Student | null;
  staff: Staff | null;
  features: { assistant?: boolean; bot?: boolean; demo?: boolean };
}

export type FieldType =
  | "text"
  | "textarea"
  | "number"
  | "select"
  | "multiselect"
  | "bool"
  | "date"
  | "file";

export interface TemplateField {
  name: string;
  type: FieldType;
  label: string;
  required?: boolean;
  options?: string[] | null;
  placeholder?: string | null;
  hint?: string | null;
  default?: unknown;
  min?: number | null;
  max?: number | null;
  minLength?: number | null;
  maxLength?: number | null;
  accept?: string[] | null;
  maxSizeMb?: number | null;
}

export interface Template {
  key: string;
  title: string;
  short_title: string;
  description: string;
  icon: string;
  category: string;
  sla_days: number;
  produces_document: boolean;
  fields: TemplateField[];
}

export interface RequestEvent {
  to_status: string;
  status_title: string;
  actor_name: string;
  actor_kind: string;
  comment: string;
  created_at: string;
}

export interface DocumentInfo {
  uuid: string;
  file_name: string;
  issued_by: string;
  issued_at: string;
  valid_until: string | null;
  revoked: boolean;
  download_url: string;
  verify_url: string;
}

export interface CampusRequest {
  id: number;
  public_no: string;
  template_key: string;
  title: string;
  icon: string;
  status: string;
  status_title: string;
  is_active: boolean;
  comment: string;
  created_at: string;
  updated_at: string;
  due_at: string | null;
  payload: Record<string, unknown>;
  events: RequestEvent[];
  document: DocumentInfo | null;
  student_name?: string | null;
  student_group?: string | null;
}

export interface CampusEvent {
  id: number;
  title: string;
  description: string;
  kind: string;
  kind_title: string;
  starts_at: string;
  ends_at: string | null;
  location: string;
  organizer_name: string;
  cover_url: string;
  capacity: number;
  taken: number;
  registration_required: boolean;
  my_status: string | null;
  details: Details;
}

/** Практика: куда прийти, что взять, как участвовать, к кому обращаться. */
export interface Details {
  place?: string;
  address?: string;
  when_text?: string;
  format?: string;
  steps?: string[];
  bring?: string[];
  requirements?: string[];
  perks?: string[];
  contact?: { name: string; role?: string; where?: string };
}

export interface Opportunity {
  id: number;
  title: string;
  description: string;
  kind: string;
  kind_title: string;
  level: string;
  level_title: string;
  organizer: string;
  url: string;
  cover_url: string;
  registration_deadline: string | null;
  days_left: number | null;
  team_size_min: number;
  team_size_max: number;
  prize_text: string;
  tags: string[];
  moderation_status: string;
  source: string;
  my_interest: string | null;
  score: number;
  details: Details;
}

export interface Intent {
  id: number;
  kind: string;
  kind_title: string;
  title: string;
  description: string;
  tags: string[];
  author_name: string;
  author_photo: string;
  author_course: number | null;
  author_faculty: string | null;
  opportunity_title: string | null;
  created_at: string;
  score: number;
}

export interface Match {
  id: number;
  origin: string;
  partner_name: string;
  partner_username: string;
  partner_photo: string;
  about: string;
  created_at: string;
}

export interface MatchProfile {
  bio: string;
  tags: string[];
  district: string;
  wants_mentor: boolean;
  wants_mentee: boolean;
  visible: boolean;
}

export interface Home {
  greeting: string;
  active_requests: CampusRequest[];
  upcoming_events: CampusEvent[];
  recommended: Opportunity[];
  deck_size: number;
  new_matches: number;
}

export interface Source {
  title: string;
  url: string;
  snippet: string;
}

export interface AssistantAction {
  type: string;
  label?: string;
  template_key?: string;
  request_no?: string;
}

export interface AskResult {
  answer: string;
  sources: Source[];
  actions: AssistantAction[];
  tools_used: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  created_at: string;
}

export interface ChatHistory {
  messages: ChatMessage[];
  suggestions: string[];
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

/* ── Учёба ─────────────────────────────────────────────────────── */

export interface Slot {
  id: number;
  pair_no: number;
  starts: string;
  ends: string;
  subject: string;
  kind: string;
  teacher: string;
  room: string;
  building_code: string;
  building_name: string;
}

export interface ScheduleDay {
  date: string;
  weekday: string;
  is_today: boolean;
  slots: Slot[];
}

export interface Week {
  group_name: string;
  week_no: number;
  parity: "odd" | "even";
  days: ScheduleDay[];
}

export interface TodayItem {
  kind: "pair" | "event" | "deadline" | "request";
  time: string;
  ends: string;
  title: string;
  subtitle: string;
  state: "now" | "next" | "done" | "";
  ref: string;
}

export interface Today {
  date: string;
  weekday: string;
  week_no: number;
  parity: "odd" | "even";
  now: Slot | null;
  next: Slot | null;
  next_day_label: string;
  items: TodayItem[];
}

export interface GradeItemInfo {
  title: string;
  points: number;
  max_points: number;
  graded_at: string;
}

export interface SubjectGrades {
  subject: string;
  control: string;
  teacher: string;
  points: number;
  max_points: number;
  forecast: string;
  items: GradeItemInfo[];
}

export interface Grades {
  semester: string;
  total_points: number;
  total_max: number;
  subjects: SubjectGrades[];
}

export interface BuildingInfo {
  code: string;
  name: string;
  address: string;
  hint: string;
  floors: number;
  cover_url: string;
  map_url: string;
}

export interface Ticket {
  code: string;
  qr_svg: string;
  event_id: number;
  event_title: string;
  when: string;
  location: string;
  holder: string;
  status: string;
}

export interface TicketCheck {
  ok: boolean;
  already: boolean;
  holder: string;
  group_name: string;
  event_title: string;
}

export interface Poll {
  id: number;
  question: string;
  options: string[];
  counts: number[];
  my_vote: number | null;
  voted: number;
  closes_at: string | null;
  event_id: number | null;
  mine: boolean;
}

export interface Group {
  group_name: string;
  members: number;
  is_head: boolean;
  head_name: string;
  polls: Poll[];
  /** Демо-профиль: опросы видит только автор, рассылки группе нет */
  demo?: boolean;
}
