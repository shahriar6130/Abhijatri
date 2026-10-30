/**
 * Client-side checks for the account forms. They give instant, kind feedback; the API repeats
 * every one of them (API.md 5.17) and its answer wins. A problem is a stable code, and the page
 * turns it into a sentence in the reader's language, so no sentence is ever assembled across
 * languages (UI-Architecture L9).
 */

export type FieldProblem = 'REQUIRED' | 'INVALID_VALUE' | 'TOO_SHORT' | 'TOO_LONG' | 'WEAK';

export const PASSWORD_MIN = 10;
export const PASSWORD_MAX = 128;
export const DISPLAY_NAME_MAX = 80;

const EMAIL = /^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}$/;

export const normalizeEmail = (value: string): string => value.normalize('NFKC').trim().toLowerCase();

export function emailProblem(value: string): FieldProblem | null {
  const email = normalizeEmail(value);
  if (!email) return 'REQUIRED';
  return EMAIL.test(email) ? null : 'INVALID_VALUE';
}

/** Same rules as the API: 10 to 128 characters, at least one letter and one digit. Paste is allowed. */
export function passwordProblem(value: string): FieldProblem | null {
  if (!value) return 'REQUIRED';
  if (value.length < PASSWORD_MIN) return 'TOO_SHORT';
  if (value.length > PASSWORD_MAX) return 'TOO_LONG';
  return /[A-Za-z]/.test(value) && /\d/.test(value) ? null : 'WEAK';
}

export function displayNameProblem(value: string): FieldProblem | null {
  const name = value.normalize('NFC').trim();
  if (!name) return 'REQUIRED';
  if (name.length > DISPLAY_NAME_MAX) return 'TOO_LONG';
  return name.includes('@') ? 'INVALID_VALUE' : null; // the name is shown beside a published review, so it must not be an email
}

/** Strength hint for the password field; the API stays the judge. */
export function passwordStrength(value: string): 0 | 1 | 2 | 3 {
  if (passwordProblem(value) !== null) return value.length >= 6 ? 1 : 0;
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((rule) => rule.test(value)).length;
  return value.length >= 14 && variety >= 3 ? 3 : 2;
}
