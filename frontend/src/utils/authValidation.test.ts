import { describe, expect, it } from 'vitest';
import { displayNameProblem, emailProblem, normalizeEmail, passwordProblem, passwordStrength } from './authValidation';

describe('emailProblem', () => {
  it('accepts ordinary addresses and ignores case and spaces', () => {
    expect(emailProblem('  Rafi@Example.COM ')).toBeNull();
    expect(normalizeEmail('  Rafi@Example.COM ')).toBe('rafi@example.com');
  });
  it('rejects empty and malformed values', () => {
    expect(emailProblem('')).toBe('REQUIRED');
    for (const bad of ['plain', 'a@b', 'a b@c.co', '@c.co', 'a@@c.co']) expect(emailProblem(bad)).toBe('INVALID_VALUE');
  });
});

describe('passwordProblem (same rules as the API)', () => {
  it('needs 10 to 128 characters with a letter and a digit', () => {
    expect(passwordProblem('Passw0rdTest99')).toBeNull();
    expect(passwordProblem('')).toBe('REQUIRED');
    expect(passwordProblem('short1')).toBe('TOO_SHORT');
    expect(passwordProblem('a1'.repeat(70))).toBe('TOO_LONG');
    expect(passwordProblem('alllettersnodigit')).toBe('WEAK');
    expect(passwordProblem('1234567890123')).toBe('WEAK');
  });
  it('allows spaces and symbols (paste friendly)', () => {
    expect(passwordProblem('correct horse 9 battery')).toBeNull();
  });
});

describe('displayNameProblem', () => {
  it('requires a name of at most 80 characters, trimmed', () => {
    expect(displayNameProblem('  Nila  ')).toBeNull();
    expect(displayNameProblem('   ')).toBe('REQUIRED');
    expect(displayNameProblem('x'.repeat(81))).toBe('TOO_LONG');
    expect(displayNameProblem('রাফি')).toBeNull();
  });
});

describe('passwordStrength', () => {
  it('only rises with a valid, varied, longer password', () => {
    expect(passwordStrength('abc')).toBe(0);
    expect(passwordStrength('abcdefg')).toBe(1);
    expect(passwordStrength('passw0rdtest')).toBe(2);
    expect(passwordStrength('Passw0rdTest99')).toBe(3);
    expect(passwordStrength('Correct-Horse-9-Battery')).toBe(3);
  });
});
