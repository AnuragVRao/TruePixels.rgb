import { useEffect, useState } from 'react';
import { ApiError, apiBlob, apiPath } from '../api/client';

export type BlobState =
  | { status: 'loading' }
  | { status: 'ready'; url: string }
  | { status: 'error'; error: unknown };

/**
 * Fetch an authenticated file and expose it as a blob: URL.
 *
 * The request carries the Bearer header (no token in any URL). The object URL
 * is revoked, and an in-flight request aborted, when the component unmounts or
 * the source changes - so blobs never accumulate.
 */
export function useAuthBlob(url: string | null): BlobState {
  const [state, setState] = useState<BlobState>({ status: 'loading' });

  useEffect(() => {
    if (!url) {
      setState({ status: 'error', error: new ApiError('NO_URL', 'No file to show.', 0) });
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setState({ status: 'loading' });
    apiBlob(apiPath(url), controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setState({ status: 'ready', url: objectUrl });
      })
      .catch((error: unknown) => {
        if ((error as Error).name !== 'AbortError') setState({ status: 'error', error });
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  return state;
}
