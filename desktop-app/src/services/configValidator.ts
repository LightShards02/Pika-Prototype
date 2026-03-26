import Ajv2020 from 'ajv/dist/2020';
import type { ErrorObject } from 'ajv';

let validateFn: ReturnType<InstanceType<typeof Ajv2020>['compile']> | null = null;

export interface ValidationError {
  path: string;
  message: string;
  keyword: string;
}

/** Load and compile the config JSON schema. Call once on mount. */
export async function loadSchema(): Promise<void> {
  if (validateFn) return;

  const pikaRoot = await window.electronAPI.getPikaRoot();
  const schemaContent = await window.electronAPI.readFile(
    pikaRoot + '/config/config.schema.json'
  );
  const schema = JSON.parse(schemaContent);

  const ajv = new Ajv2020({ allErrors: true, strict: false });
  validateFn = ajv.compile(schema);
}

/** Validate config data against the compiled schema. Returns empty array if valid. */
export function validateConfig(data: Record<string, unknown>): ValidationError[] {
  if (!validateFn) return [];

  const valid = validateFn(data);
  if (valid) return [];

  return (validateFn.errors ?? []).map((err: ErrorObject) => ({
    path: err.instancePath || '/',
    message: err.message ?? 'Unknown validation error',
    keyword: err.keyword,
  }));
}

/** Format errors into human-readable strings. */
export function formatValidationErrors(errors: ValidationError[]): string[] {
  return errors.map(e => {
    const field = e.path === '/' ? 'root' : e.path.replace(/\//g, '.').slice(1);
    return `${field}: ${e.message}`;
  });
}
