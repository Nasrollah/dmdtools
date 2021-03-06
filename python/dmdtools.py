import numpy as np

def dmd(X, Y):
    """Compute DMD modes and eigenvalues for data matrices X and Y"""
    Qx, S, Vt = np.linalg.svd(X, full_matrices=False)
    V = Vt.T
    Sinv = np.diag(1./S)
    Ktilde = Qx.T.dot(Y).dot(V).dot(Sinv)
    evals, evecK = np.linalg.eig(Ktilde)
    modes = Qx.dot(evecK)
    return modes, evals

def polynomial_kernel(X, Y, n):
    return (1 + np.dot(X.T, Y)) ** n

def kdmd(X, Y, kernel=None):
    """Compute Koopman modes and eigenvalues using kernel DMD

    Parameters
    ----------
    X : array
        Input array whose columns are snapshots at initial times
    Y : array
        Input array whose columns are snapshots at final times
    kernel : int or callable, optional
        If None (default) or zero, use kernel f(x,y) = x'y
        If integer ``n``, use polynomial kernel f(x,y) = (1 + x'y)^n
        If callable ``kernel``, use custom f(x,y) = kernel(x, y)

    Returns
    -------
    modes : array
        Array whose columns are Koopman modes
    evals : array
        DMD eigenvalues
    """
    if kernel is None or kernel == 0:
        # standard DMD
        G = np.dot(X.T, X)
        A = np.dot(Y.T, X)
    elif type(kernel) is int:
        # use the polynomial kernel: (1 + x.y)^n
        G = polynomial_kernel(X, X, kernel)
        A = polynomial_kernel(Y, X, kernel)
    else:
        # use a custom kernel
        G = kernel(X, X)
        A = kernel(Y, X)
    K = np.dot(np.linalg.pinv(G), A)
    evals, evecs = np.linalg.eig(K.T)
    Ginv = np.linalg.pinv(G)
    modes = np.dot(X, np.dot(Ginv, evecs))
    return modes, evals


class StreamingDMD:
    def __init__(self, max_rank=None, ngram=5, epsilon=1.e-10):
        self.max_rank = max_rank
        self.count = 0
        self.ngram = ngram      # number of times to reapply Gram-Schmidt
        self.epsilon = epsilon  # tolerance for expanding the bases

    def update(self, x, y):
        """Update the DMD computation with a pair of snapshots

        Add a pair of snapshots (x,y) to the data ensemble.  Here, if the
        (discrete-time) dynamics are given by z(n+1) = f(z(n)), then (x,y)
        should be measurements corresponding to consecutive states
        z(n) and z(n+1)
        """

        self.count += 1
        normx = np.linalg.norm(x)
        normy = np.linalg.norm(y)
        n = len(x)

        x = np.asmatrix(x).reshape((n, 1))
        y = np.asmatrix(y).reshape((n, 1))

        # process the first iterate
        if self.count == 1:
            # construct bases
            self.Qx = x / normx
            self.Qy = y / normy

            # compute
            self.Gx = np.matrix(normx**2)
            self.Gy = np.matrix(normy**2)
            self.A = np.matrix(normx * normy)
            return

        # ---- Algorithm step 1 ----
        # classical Gram-Schmidt reorthonormalization
        rx = self.Qx.shape[1]
        ry = self.Qy.shape[1]
        xtilde = np.matrix(np.zeros((rx, 1)))
        ytilde = np.matrix(np.zeros((ry, 1)))
        ex = np.matrix(x).reshape((n, 1))
        ey = np.matrix(y).reshape((n, 1))
        for i in range(self.ngram):
            dx = self.Qx.T.dot(ex)
            dy = self.Qy.T.dot(ey)
            xtilde += dx
            ytilde += dy
            ex -= self.Qx.dot(dx)
            ey -= self.Qy.dot(dy)

        # ---- Algorithm step 2 ----
        # check basis for x and expand, if necessary
        if np.linalg.norm(ex) / normx > self.epsilon:
            # update basis for x
            self.Qx = np.bmat([self.Qx, ex / np.linalg.norm(ex)])
            # increase size of Gx and A (by zero-padding)
            self.Gx = np.bmat([[self.Gx, np.zeros((rx, 1))],[np.zeros((1,rx+1))]])
            self.A = np.bmat([self.A, np.zeros((ry, 1))])
            rx += 1

        # check basis for y and expand if necessary
        if np.linalg.norm(ey) / normy > self.epsilon:
            # update basis for y
            self.Qy = np.bmat([self.Qy, ey / np.linalg.norm(ey)])
            # increase size of Gy and A (by zero-padding)
            self.Gy = np.bmat([[self.Gy, np.zeros((ry,1))],[np.zeros((1,ry+1))]])
            self.A = np.bmat([[self.A],[np.zeros((1,rx))]])
            ry += 1

        # ---- Algorithm step 3 ----
        # check if POD compression is needed
        r0 = self.max_rank
        if r0:
            if rx > r0:
                evals, evecs = np.linalg.eig(self.Gx)
                idx = np.argsort(evals)
                idx = idx[-1:-1-r0:-1]   # indices of largest r0 eigenvalues
                qx = np.asmatrix(evecs[:,idx])
                self.Qx = self.Qx * qx
                self.A = self.A * qx
                self.Gx = np.asmatrix(np.diag(evals[idx]))
            if ry > r0:
                evals, evecs = np.linalg.eig(self.Gy)
                idx = np.argsort(evals)
                idx = idx[-1:-1-r0:-1]   # indices of largest r0 eigenvalues
                qy = np.asmatrix(evecs[:,idx])
                self.Qy = self.Qy * qy
                self.A = qy.T * self.A
                self.Gy = np.asmatrix(np.diag(evals[idx]))

        # ---- Algorithm step 4 ----
        xtilde = self.Qx.T * x
        ytilde = self.Qy.T * y

        # update A and Gx
        self.A  += ytilde * xtilde.T
        self.Gx += xtilde * xtilde.T
        self.Gy += ytilde * ytilde.T

    def compute_matrix(self):
        return self.Qx.T.dot(self.Qy).dot(self.A).dot(np.linalg.pinv(self.Gx))

    def compute_modes(self):
        Ktilde = self.compute_matrix()
        evals, evecK = np.linalg.eig(Ktilde)
        modes = self.Qx.dot(evecK)
        return modes, evals
