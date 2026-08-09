/**
 * The app's icon set (issue #340).
 *
 * **Why a component library rather than an icon font.** Icons used to be
 * ligatures in a self-hosted Material Symbols font. That failed twice over: a
 * font loaded from a CDN was blocked by the desktop shell's CSP, and even
 * self-hosted, an icon was just a string handed to a font, so a typo rendered
 * as literal text with nothing to catch it. `lucide-react` ships each icon as
 * a tree-shakeable React component drawing inline SVG, so there is no font to
 * load, nothing for a CSP to block, and no text to leak when a lookup fails.
 *
 * **The naming convention, and why it is not lucide's.** Keys here are the
 * Material Symbols names the app used before the migration. They are kept
 * because they are *data*: a room's icon and a badge's icon are persisted on
 * the server and chosen by users, so renaming the vocabulary would orphan
 * rows that already reference it. The table is therefore a deliberate
 * indirection between a stored name and whichever library draws it — not an
 * accident of the migration.
 *
 * **For a future React Native target.** That indirection is the thing to
 * reuse. `lucide-react-native` exposes the same icon components under the
 * same export names, so a native build reimplements only the `Icon` component
 * itself — swapping the import and the className styling for its own — while
 * this table, `IconName` and `resolveIconName` carry across unchanged. Stored
 * icon names keep meaning the same thing on every platform, which is the
 * property that matters and the one a per-platform icon list would lose.
 */
import {
  Award,
  Ban,
  Bed,
  BellRing,
  BookOpen,
  Brain,
  BrainCircuit,
  Briefcase,
  Camera,
  Check,
  ChevronDown,
  Circle,
  CircleAlert,
  CircleCheckBig,
  CircleHelp,
  CirclePlay,
  CirclePlus,
  Compass,
  DoorOpen,
  Eye,
  EyeOff,
  FileText,
  FileUp,
  Flame,
  FlaskConical,
  Footprints,
  GraduationCap,
  History,
  Hourglass,
  Info,
  Languages,
  LayoutDashboard,
  Layers,
  Library,
  Lightbulb,
  Link,
  LoaderCircle,
  LogOut,
  Mail,
  Monitor,
  Moon,
  Network,
  PartyPopper,
  Pencil,
  Plane,
  Plus,
  ArrowLeft,
  RotateCw,
  Route,
  Slash,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  Sun,
  Tag,
  ThumbsDown,
  ThumbsUp,
  Timer,
  Trash2,
  TrendingUp,
  User,
  UtensilsCrossed,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react'

// Icon names follow the Material Symbols vocabulary this app used before
// migrating to lucide-react, so existing UI copy, room/badge icon values
// persisted by the backend, and call sites didn't need to change.
const ICONS = {
  add: Plus,
  add_circle: CirclePlus,
  arrow_back: ArrowLeft,
  auto_awesome: Sparkles,
  bed: Bed,
  bedtime: Moon,
  block: Ban,
  bolt: Zap,
  category: Layers,
  celebration: PartyPopper,
  check: Check,
  // Referenced by OAuthAuthorizePage but never defined, so both were quietly
  // rendering the fallback glyph until `IconName` made it a compile error.
  check_circle: CircleCheckBig,
  radio_button_unchecked: Circle,
  circle: Circle,
  close: X,
  delete: Trash2,
  desktop_windows: Monitor,
  expand_more: ChevronDown,
  directions_walk: Footprints,
  edit: Pencil,
  error: CircleAlert,
  explore: Compass,
  flight: Plane,
  hourglass_empty: Hourglass,
  hub: Network,
  info: Info,
  label: Tag,
  lightbulb: Lightbulb,
  link: Link,
  local_fire_department: Flame,
  local_library: Library,
  logout: LogOut,
  mail: Mail,
  meeting_room: DoorOpen,
  memory: BrainCircuit,
  menu_book: BookOpen,
  monitoring: TrendingUp,
  notifications_active: BellRing,
  person: User,
  phone_iphone: Smartphone,
  play_circle: CirclePlay,
  progress_activity: LoaderCircle,
  psychology: Brain,
  quiz: CircleHelp,
  // The deliberate landing place for a stored icon name this build does not
  // have — a rename outliving the data that referenced it.
  unknown: Slash,
  refresh: RotateCw,
  restaurant: UtensilsCrossed,
  route: Route,
  school: GraduationCap,
  science: FlaskConical,
  screenshot_monitor: Camera,
  space_dashboard: LayoutDashboard,
  style: Layers,
  task_alt: CircleCheckBig,
  text_snippet: FileText,
  thumb_down: ThumbsDown,
  thumb_up: ThumbsUp,
  timer: Timer,
  translate: Languages,
  tune: SlidersHorizontal,
  update: History,
  upload_file: FileUp,
  visibility: Eye,
  visibility_off: EyeOff,
  wb_sunny: Sun,
  work: Briefcase,
  workspace_premium: Award,
  // `satisfies` rather than a type annotation: annotating this as
  // `Record<string, LucideIcon>` would widen the keys back to `string` and
  // make `IconName` below mean nothing, which is the entire bug this change
  // exists to fix. `satisfies` checks every value is an icon while keeping
  // the literal key names.
} satisfies Record<string, LucideIcon>

/**
 * Every icon this app can render.
 *
 * The point of the type (issue #340): `<Icon name="meeting_rom" />` is a
 * compile error rather than something that renders a fallback glyph nobody
 * notices in review. Migrating off the ligature font stopped a typo rendering
 * as literal text, but a `name: string` prop over a lookup table still meant
 * the mistake survived to runtime — quieter, and no easier to catch.
 */
export type IconName = keyof typeof ICONS

/**
 * Narrow a runtime string to an icon name.
 *
 * Some icon names are *data*: a room's `icon` and a badge's `icon` are stored
 * on the server and chosen by the user, so they cannot be checked at compile
 * time and must not pretend to be. This is the one sanctioned way in, and it
 * is deliberately explicit — a call site that uses it is visibly saying "this
 * value came from outside the code", which a silent `as IconName` cast would
 * hide.
 *
 * `fallback` is the icon to show when the stored value names something this
 * build does not have, which is what happens when data outlives a rename.
 */
export function resolveIconName(value: string, fallback: IconName = 'unknown'): IconName {
  return value in ICONS ? (value as IconName) : fallback
}

export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  // The fallback stays for `resolveIconName`'s benefit: stored data can still
  // name an icon this build does not have, and a missing glyph is a better
  // outcome than a crash mid-render.
  const Glyph = ICONS[name] ?? Slash
  return <Glyph className={`inline-block h-[1em] w-[1em] shrink-0 align-[-0.125em] ${className}`} aria-hidden="true" />
}
